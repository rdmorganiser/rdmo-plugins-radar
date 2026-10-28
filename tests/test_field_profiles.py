"""Public field strategies work with independent catalog profiles in both directions."""
import ast
from dataclasses import FrozenInstanceError, replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Value

from examples.custom_mapping import make_mapping
from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExport, RadarExportProvider
from rdmo_radar.factories import build_export_service, build_import_service, build_xml_export_service
from rdmo_radar.imports import RadarImport
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.fields import (
    AffiliationDestinations,
    AffiliationSources,
    Coordinates,
    Destination,
    FieldMapping,
    FundingDestinations,
    FundingSources,
    GroupSpec,
    IdentifierDestinations,
    IdentifierSource,
    PersonDestinations,
    PersonSources,
    Source,
    read_funding,
    read_language,
    read_people,
    read_text,
    write_funding,
    write_people,
)
from rdmo_radar.metadata.importer import write_metadata
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.types import Affiliation, FundingReference, Identifier, PersonOrOrganization, RadarMetadata
from rdmo_radar.metadata.write_context import ProjectWriteContext


def attribute(path, namespace):
    parent, _, key = path.rpartition('/')
    return Attribute.objects.get_or_create(
        key=key, parent=attribute(parent, namespace) if parent else None, uri_prefix=namespace,
    )[0]


@pytest.mark.parametrize('namespace,base,prefix,suffix', [
    ('https://first.test', 'records', '', ()),
    ('https://second.test', 'study/material', '8', (0,)),
])
def test_standalone_profile_exports_imports_and_stores_without_tf_configuration(
    db, django_assert_num_queries, namespace, base, prefix, suffix,
):
    selectors = {key: attribute(f'{base}/{path}', namespace) for key, path in {
        'title': 'caption', 'language': 'locale', 'person_name': 'team/display', 'person_id': 'team/persistent',
        'person_id_type': 'team/scheme', 'person_type': 'team/kind', 'radar_id': 'repository/id',
        'radar_url': 'repository/link',
    }.items()}
    options = {key: Option.objects.create(uri_prefix=namespace, uri_path=path) for key, path in {
        'language': 'spoken/de', 'identifier': 'identities/orcid', 'name_type': 'entities/person',
    }.items()}
    profile = make_mapping(
        **{key: item.uri for key, item in selectors.items()},
        language_options={options['language'].uri: 'deu'},
        identifier_options={options['identifier'].uri: 'ORCID'},
        name_type_options={options['name_type'].uri: 'Personal'},
        import_prefix=prefix, person_prefix_suffix=suffix,
    )
    project = Project.objects.create(title='Independent catalog')
    orcid = '0000-0002-1825-0097'
    for index in (3, 10):
        project.values.create(attribute=selectors['title'], text=f'Record {index}', set_prefix=prefix, set_index=index)
        project.values.create(attribute=selectors['language'], text='Deutsch', set_prefix=prefix, set_index=index)
        child_prefix = '|'.join(filter(None, (prefix, str(index), *map(str, suffix))))
        project.values.create(attribute=selectors['person_name'], text=f'Person {index}', set_prefix=child_prefix)
        project.values.create(attribute=selectors['person_id'], text=orcid, set_prefix=child_prefix)
        project.values.create(
            attribute=selectors['person_id_type'], option=options['identifier'], set_prefix=child_prefix
        )
    # Prepared lookup cannot borrow populated TF fields.
    project.values.create(attribute=attribute('project/dataset/language', 'https://unrelated.test'), text='French')

    with django_assert_num_queries(1):
        rest = build_export_service(project, profile=profile, collect_mapping=True)
    with django_assert_num_queries(0):
        datasets = profile.get_datasets(project, rest.reader)
        assert [item.label for item in datasets] == ['Record 3', 'Record 10']
        payloads = [rest.compute_payload(item, 'owner@example.test') for item in datasets]
        assert [item.payload['descriptiveMetadata']['language'] for item in payloads] == ['DEU', 'DEU']
        assert [item.payload['descriptiveMetadata']['creators']['creator'][0]['creatorName']
                for item in payloads] == ['Person 3', 'Person 10']
        metadata = rest.mapping(rest.reader(datasets[0])).metadata
    assert metadata.creators[0].identifiers == [Identifier(orcid, 'ORCID')]
    assert not payloads[0].issues
    assert all(
        source.reference.startswith(namespace)
        for attempt in payloads[0].provenance
        for source in attempt.sources
        if isinstance(source.value, Value)
    )
    xml = build_xml_export_service(project, profile=profile).compute_files(datasets)
    assert all(ElementTree.fromstring(item.xml_data).findtext(
        '{http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements}language',
    ) == 'deu' for item in xml)

    plugin = SimpleNamespace(values=[], current_project=project,
                             get_attribute={item.uri: item for item in selectors.values()}.get,
                             get_option={item.uri: item for item in options.values()}.get)
    persisted = list(project.values.values())
    with django_assert_num_queries(1):
        importing = build_import_service(plugin, profile=profile, parser=lambda value: value)
    with django_assert_num_queries(0):
        assert importing.process(metadata) == ()
    assert all(value.pk is None for value in plugin.values)
    assert [(v.set_prefix, v.set_index) for v in plugin.values if v.attribute_id == selectors['title'].pk] == [
        (prefix, 11)
    ]
    expected_child = '|'.join(filter(None, (prefix, '11', *map(str, suffix))))
    assert [(v.set_prefix, v.set_index) for v in plugin.values if v.attribute_id == selectors['person_name'].pk] == [
        (expected_child, 0),
    ]
    assert list(project.values.values()) == persisted
    rest.store_result(datasets[0], 'confirmed', 'https://radar.test/confirmed')
    assert project.values.get(attribute=selectors['radar_id']).text == 'confirmed'
    assert project.values.get(attribute=selectors['radar_url']).set_prefix == prefix


def test_field_configuration_is_validated_and_frozen():
    callbacks = {'title': lambda context, *, target: 'Title'}
    configured = FieldMapping(readers=callbacks)
    callbacks.clear()
    assert list(configured.readers) == ['title']
    with pytest.raises(TypeError):
        configured.readers['title'] = None
    with pytest.raises(FrozenInstanceError):
        configured.readers = {}
    with pytest.raises(ValueError, match='Unknown canonical'):
        FieldMapping(readers={'invented': lambda context: None})
    with pytest.raises(TypeError, match='callable'):
        FieldMapping(writers={'title': None})


def test_source_and_normalizer_are_independently_replaceable():
    path = 'https://custom.test/domain/spoken'
    value = Value(attribute=Attribute(uri=path, uri_prefix='https://custom.test', path='spoken'), text='local-language')
    context = ProjectReadContext({path: [value]}, {}, provenance=[])
    fields = FieldMapping(
        readers={
            'language': partial(
                read_language,
                source=Source(path),
                option_map={},
                normalizer=lambda value: 'dan' if value == 'local-language' else None,
            )
        }
    )
    result = compute_metadata(context, fields=fields)
    assert result.metadata.language == 'dan'
    assert result.metadata.title is None
    assert result.provenance[0].field == 'language'
    assert result.provenance[0].sources[0].reference == path
    changed = replace(fields, readers={'title': partial(read_text, source=Source(path), normalizer=str.upper)})
    assert compute_metadata(context, fields=changed).metadata.title == 'LOCAL-LANGUAGE'


def test_import_crosswalk_is_independent_and_unconfigured_fields_warn():
    path = 'https://custom.test/domain/locale'
    locale = Attribute(uri=path, uri_prefix='https://custom.test', path='locale')
    chosen = Option(uri='https://custom.test/options/chosen', uri_prefix='https://custom.test', uri_path='chosen')
    plugin = SimpleNamespace(values=[], get_attribute={path: locale}.get, get_option={chosen.uri: chosen}.get)
    context = ProjectWriteContext(plugin, {}, Coordinates('7', 4))
    from rdmo_radar.metadata.fields import write_option
    fields = FieldMapping(writers={'language': partial(write_option, destination=Destination(path, Coordinates('7', 4)),
                                                      option_map={'deu': chosen.uri})})
    issues = write_metadata(context, RadarMetadata(language='deu', title='Unmapped'), fields=fields)
    assert [(value.option, value.set_prefix, value.set_index) for value in plugin.values] == [(chosen, '7', 4)]
    assert [(issue.field, issue.reason) for issue in issues] == [('title', 'No configured RDMO import destination')]


def memory_writer(names):
    selectors = {name: f'https://independent.test/domain/{name}' for name in names}
    attributes = {uri: Attribute(uri=uri, path=name) for name, uri in selectors.items()}
    options = {name: Option(pk=index + 1, uri=f'https://independent.test/options/{name}', uri_path=name)
               for index, name in enumerate(('ORCID', 'ROR', 'Personal'))}
    plugin = SimpleNamespace(values=[], get_attribute=attributes.get,
                             get_option={option.uri: option for option in options.values()}.get)
    return ProjectWriteContext(plugin, {}, Coordinates()), selectors, options


def staged_reader(context):
    buckets = {}
    for value in context.import_plugin.values:
        buckets.setdefault(value.attribute.uri, []).append(value)
    return ProjectReadContext(buckets, {}, provenance=[])


def test_people_and_affiliations_reuse_independent_sources_and_destinations():
    context, paths, options = memory_writer((
        'name', 'given', 'family', 'kind', 'id', 'scheme', 'institution', 'institution_id', 'institution_scheme',
    ))
    identifier_options = {name: options[name].uri for name in ('ORCID', 'ROR')}

    def destinations(index):
        def own(name):
            return Destination(paths[name], Coordinates('12', index))

        def affiliation(child_index):
            def child(name):
                return Destination(paths[name], Coordinates(f'12|{index}', child_index))
            return AffiliationDestinations(child('institution'), IdentifierDestinations(
                child('institution_id'), child('institution_scheme'), identifier_options,
            ))

        return PersonDestinations(
            name=own('name'), given_name=own('given'), family_name=own('family'), name_type=own('kind'),
            name_type_options={'Personal': options['Personal'].uri},
            identifiers=lambda child_index: IdentifierDestinations(own('id'), own('scheme'), identifier_options),
            affiliations=affiliation,
        )

    people = [PersonOrOrganization(
        name=f'Person {index}', name_type='Personal', given_name=f'Given {index}', family_name='Family',
        identifiers=[Identifier('0000-0002-1825-0097', 'ORCID')],
        affiliations=[Affiliation(f'Institution {index}', identifier, 'ROR')],
    ) for index, identifier in enumerate(('https://ror.org/0387prb75', 'https://ror.org/018mejw64'))]
    write_people(context, people, destinations=destinations, target='creators')
    assert context.issues == []
    source_options = {uri: name for name, uri in identifier_options.items()}
    sources = PersonSources(
        group=GroupSpec((paths['name'],)), name=paths['name'], given_name=paths['given'], family_name=paths['family'],
        name_type=paths['kind'], name_type_options={options['Personal'].uri: 'Personal'},
        identifiers=(IdentifierSource(paths['id'], scheme_source=paths['scheme'], option_map=source_options),),
        affiliations=AffiliationSources(paths['institution'], IdentifierSource(
            paths['institution_id'], scheme_source=paths['institution_scheme'], option_map=source_options,
        )),
    )
    read = staged_reader(context)
    assert read_people(read, sources=sources, target='creators') == people
    assert read.issues == []


def test_funding_supports_separate_name_identifier_and_grant_sources():
    context, paths, options = memory_writer(('support', 'registry', 'identifier_kind', 'award', 'programme', 'url'))
    references = [FundingReference(
        'Same name', Identifier(identifier, 'ROR'), award_number=f'Award {index}', award_title='Programme',
    ) for index, identifier in enumerate(('https://ror.org/0387prb75', 'https://ror.org/018mejw64'))]

    def destinations(index):
        def own(name):
            return Destination(paths[name], Coordinates('15', index))
        return FundingDestinations(
            funder_name=own('support'), funder_identifier=IdentifierDestinations(
                own('registry'), own('identifier_kind'), {'ROR': options['ROR'].uri},
            ), award_number=own('award'), award_title=own('programme'), award_uri=own('url'),
        )

    write_funding(context, references, destinations=destinations, target='funding_references')
    assert context.issues == []
    sources = FundingSources(
        group=GroupSpec((paths['support'],)), name=paths['support'],
        identifier=IdentifierSource(paths['registry'], scheme_source=paths['identifier_kind'],
                                    option_map={options['ROR'].uri: 'ROR'}),
        award_number=paths['award'], award_title=paths['programme'], award_uri=paths['url'],
    )
    read = staged_reader(context)
    assert read_funding(read, sources=sources, target='funding_references') == references
    assert read.issues == []


@pytest.mark.parametrize('factory', [build_export_service, build_xml_export_service, build_import_service])
def test_generic_factories_require_an_explicit_profile(factory):
    with pytest.raises(TypeError, match='profile'):
        factory(None)
    with pytest.raises(ValueError, match='explicit RADAR mapping'):
        factory(None, profile=None)


@pytest.mark.parametrize('adapter', [RadarExport, RadarExportProvider, RadarCredentialsExportProvider, RadarImport])
def test_generic_adapters_require_a_mapping(db, adapter):
    plugin = adapter('custom', 'Custom', f'{adapter.__module__}.{adapter.__name__}')
    project = Project.objects.create(title='Project')
    if isinstance(plugin, RadarImport):
        plugin.current_project = project
        call = plugin.process
    else:
        plugin.project = project
        call = plugin.get_service
    with pytest.raises(ValueError, match='explicit RADAR mapping'):
        call()


def test_confirmed_callback_without_mapping_preserves_result(db, django_assert_num_queries):
    provider = RadarExportProvider('custom', 'Custom', 'rdmo_radar.exports.RadarExportProvider')
    request = SimpleNamespace(session={})
    provider._active_export = (request, {
        'project_id': 1, 'radar_url': 'https://radar.test', 'language': 'en', 'persist': True,
        'dataset': {'key': 'record', 'label': 'Record', 'scope': {}},
    })
    provider.render_export_result = Mock(return_value='confirmed result')
    with django_assert_num_queries(0):
        assert provider.post_success(request, SimpleNamespace(json=lambda: {'id': 'confirmed'})) == 'confirmed result'
    provider.render_export_result.assert_called_once_with(
        request, 'confirmed', 'https://radar.test/radar/en/dataset/confirmed', stored=False,
    )


def test_reusable_mapping_modules_do_not_depend_on_tf():
    root = Path(__file__).parents[1] / 'rdmo_radar'
    for path in [*root.joinpath('metadata').rglob('*.py'), root / 'factories.py', root / 'exports/storage.py']:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert 'template_framework' not in (node.module or ''), path
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.startswith(('project/', 'dmp/')), path
