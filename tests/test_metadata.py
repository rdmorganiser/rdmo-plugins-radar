from functools import partial
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Value

from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import get_radar_schema, get_radar_validation_errors, validate_radar_xml
from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.imports.imports import RadarTemplateFrameworkImport as RadarImport
from rdmo_radar.mappings.template_framework import compute_metadata
from rdmo_radar.mappings.template_framework.fields import read_identifier
from rdmo_radar.mappings.template_framework.vocabulary import XMLVocabulary
from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.fields import Source, read_resource
from rdmo_radar.metadata.normalization import normalize_primary_identifier
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.types import (
    Affiliation,
    Description,
    GeoLocation,
    Identifier,
    PersonOrOrganization,
    RadarMetadata,
    Resource,
    Rights,
    SubjectArea,
)
from rdmo_radar.metadata.validation import missing_required_fields
from rdmo_radar.metadata.xml import parse_xml, to_xml_payload

from .helpers import (
    add_answer,
    complete_metadata,
    make_data_management_project,
    make_export,
    make_tf_mapping,
)


def make_import(xml):
    radar_import = RadarImport.__new__(RadarImport)
    radar_import.current_project = SimpleNamespace(
        catalog=object(),
        values=SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(select_related=lambda *args: [])),
    )
    radar_import.root = ElementTree.fromstring(xml)
    radar_import.values = []
    paths = {
        'project/dataset/title',
        'project/dataset/data_publication_pid',
        'project/dataset/pids/system',
        'project/dataset/description',
        'project/dataset/format',
        'project/dataset/creation_methods',
        'project/funder/id',
        'project/funder/name',
        'project/funder/grant_nr',
        'project/research_question/keywords',
        'project/partner/name',
        'project/partner/given_name',
        'project/partner/family_name',
        'project/partner/organization',
        'project/partner/orcid',
    }
    attributes = {path: Attribute(path=path) for path in paths}
    option_paths = {
        'identifier_type/doi',
        'resource_type_general/dataset',
        'radar_data_source/observation',
    }
    options = {path: Option(uri_path=path) for path in option_paths}
    radar_import.get_attribute = lambda uri: attributes.get(uri.removeprefix(
        'https://rdmorganiser.github.io/terms/domain/'))
    radar_import.get_option = lambda uri: options.get(uri.removeprefix(
        'https://rdmorganiser.github.io/terms/options/'))
    return radar_import


def test_only_confirmed_dataset_paths_are_read(db):
    export = make_export({
        'project/dataset/description': 'Canonical resource',
        'project/dataset/resource_type': 'Unconfirmed legacy resource',
        'project/dataset/title': 'Dataset title',
        'project/dataset/format': 'text/csv',
    })
    result = compute_metadata(export.get_service().reader(0))
    metadata = result.metadata
    assert metadata.resource == Resource('Canonical resource')
    assert metadata.title == 'Dataset title'
    assert not any(issue.source == 'project/dataset/format' for issue in result.issues)


def test_creator_name_is_derived_from_structured_parts(db):
    export = make_export()
    add_answer(export.project, 'project/dataset/creator/given_name', 'Jane', set_prefix='0')
    add_answer(export.project, 'project/dataset/creator/family_name', 'Doe', set_prefix='0')
    result = compute_metadata(export.get_service().reader(0))
    metadata = result.metadata
    assert metadata.creators[0].name == 'Doe, Jane'
    assert metadata.creators[0].given_name == 'Jane'
    assert metadata.creators[0].family_name == 'Doe'


@pytest.mark.parametrize('scheme', ['doi', 'handle', 'radar', 'url', 'other', 'unknown', None])
def test_tf_primary_identifier_requires_a_supported_scheme(db, scheme):
    export = make_export({'project/dataset/data_publication_pid': '10.1234/example'})
    if scheme is not None:
        option = Option.objects.create(uri_prefix='https://example.test', uri_path=f'identifier_type/{scheme}')
        add_answer(export.project, 'project/dataset/pids/system', '', option=option)

    result = compute_metadata(export.get_service().reader(0))

    if scheme in ('doi', 'handle', 'radar'):
        kind = {'doi': 'DOI', 'handle': 'Handle', 'radar': 'RADAR'}[scheme]
        assert result.metadata.identifier == Identifier('10.1234/example', kind)
        assert not result.issues
    else:
        assert result.metadata.identifier is None
        assert 'identifier' not in to_xml_payload(result.metadata)
        assert 'identifier' not in to_api_payload(result.metadata)
        assert any('Primary identifier requires DOI, Handle or RADAR' in issue.reason for issue in result.issues)


@pytest.mark.parametrize('namespace,schemes', [
    ('https://example.test', ('identifier_type/doi', 'identifier_type/url')),
    ('https://dmp.service.base4nfdi.de/terms', ('pid03', 'pid06')),
])
def test_tf_conflicting_primary_identifier_schemes_are_omitted(db, namespace, schemes):
    export = make_export({'project/dataset/data_publication_pid': '10.1234/example'})
    for index, scheme in enumerate(schemes):
        option = Option.objects.create(uri_prefix=namespace, uri_path=scheme)
        add_answer(export.project, 'project/dataset/pids/system', '', option=option, collection_index=index)
    context = export.get_service().reader(0)
    context.provenance = []

    result = compute_metadata(context)

    assert result.metadata.identifier is None
    assert any(attempt.field == 'identifier.value' and attempt.outcome == 'rejected'
               for attempt in result.provenance)


@pytest.mark.parametrize('namespace,path,expected', [
    *[('https://dmp.service.base4nfdi.de/terms', f'pid{index:02}',
       'DOI' if index == 3 else 'Handle' if index == 6 else None) for index in range(19)],
    ('https://unrelated.test', 'pid03', None),
])
def test_tf_catalog_pid_aliases_require_exact_option_identity(db, namespace, path, expected):
    export = make_export({'project/dataset/data_publication_pid': '10.1234/example'})
    option = Option.objects.create(uri_prefix=namespace, uri_path=path, text_lang1='Misleading display label')
    add_answer(export.project, 'project/dataset/pids/system', '', option=option)
    result = compute_metadata(export.get_service().reader(0))
    if expected:
        assert result.metadata.identifier == Identifier('10.1234/example', expected)
        assert to_xml_payload(result.metadata)['identifierType'] == expected
        assert to_api_payload(result.metadata)['identifier']['identifierType'] == expected.upper()
        assert not result.issues
    else:
        assert result.metadata.identifier is None
        assert result.issues


@pytest.mark.parametrize('path', ['pid03', 'pid01'])
def test_tf_planned_pid_without_a_publication_identifier_is_skipped(db, path):
    export = make_export()
    option = Option.objects.create(uri_prefix='https://dmp.service.base4nfdi.de/terms', uri_path=path)
    answer = add_answer(export.project, 'project/dataset/pids/system', '', option=option)
    context = export.get_service().reader(0)
    context.provenance = []
    result = compute_metadata(context)
    assert result.metadata.identifier is None
    assert not result.issues
    attempt = next(a for a in result.provenance if a.field == 'identifier.identifier_type')
    assert attempt.outcome == 'skipped'
    assert 'Planned PID system' in attempt.reason
    assert attempt.sources[0].value.pk == answer.pk


def test_tf_conflicting_publication_pids_are_not_reported_as_planned_only(db):
    export = make_export({'project/dataset/data_publication_pid': '10.1234/first'})
    add_answer(export.project, 'project/dataset/data_publication_pid', '10.1234/second', collection_index=1)
    option = Option.objects.create(uri_prefix='https://dmp.service.base4nfdi.de/terms', uri_path='pid03')
    add_answer(export.project, 'project/dataset/pids/system', '', option=option)
    context = export.get_service().reader(0)
    context.provenance = []
    result = compute_metadata(context)
    assert result.metadata.identifier is None
    assert result.issues
    attempt = next(a for a in result.provenance if a.field == 'identifier.identifier_type')
    assert attempt.reason == 'Publication PID is unusable; identifier scheme not applied'


def test_xml_and_api_adapters_share_canonical_model_but_not_wire_values():
    metadata = RadarMetadata(
        identifier=Identifier('10.1234/example', 'DOI'),
        creators=[PersonOrOrganization(
            name='Doe, Jane',
            name_type='Personal',
            affiliations=[Affiliation('First University'), Affiliation('Second University')],
        )],
        resource=Resource('Research data', 'Dataset'),
        rights=Rights('CC BY 4.0 Attribution'),
    )

    xml_data = to_xml_payload(metadata)
    api_data = to_api_payload(metadata)

    assert metadata.resource.resource_type == 'Dataset'
    assert xml_data['resource']['resourceType'] == 'Dataset'
    assert api_data['resource']['resourceType'] == 'DATASET'
    assert xml_data['creators']['creator'][0]['creatorAffiliation'] == 'First University'
    assert api_data['creators']['creator'][0]['creatorAffiliation'] == {'value': 'First University'}


def test_xml_parser_preserves_canonical_rddm_values():
    xml = RadarExportRenderer().render({
        'identifier': '10.1234/example',
        'identifierType': 'DOI',
        'creators': {'creator': [{'creatorName': 'Doe, Jane'}]},
        'title': 'Dataset',
        'publishers': {'publisher': ['Repository']},
        'productionYear': '2026',
        'subjectAreas': {'subjectArea': [{'controlledSubjectAreaName': 'Chemistry'}]},
        'resource': {'value': 'Research data', 'resourceType': 'Dataset'},
        'rights': {'controlledRights': 'CC BY 4.0 Attribution'},
        'rightsHolders': {'rightsHolder': ['University']},
        'version': '2.1',
    })

    metadata = parse_xml(ElementTree.fromstring(xml))

    assert metadata.identifier == Identifier('10.1234/example', 'DOI')
    assert metadata.creators[0].name == 'Doe, Jane'
    assert metadata.publishers[0].name == 'Repository'
    assert metadata.resource == Resource('Research data', 'Dataset')
    assert metadata.version == '2.1'


def test_semantic_metadata_serializes_to_valid_rddm_9_3_xml():
    metadata = RadarMetadata(
        identifier=Identifier('10.1234/example', 'DOI'),
        creators=[PersonOrOrganization(
            name='Doe, Jane',
            affiliations=[Affiliation('Example University', 'https://ror.org/example', 'ROR')],
        )],
        title='Dataset',
        additional_titles=['DATA'],
        descriptions=[Description('Description')],
        publishers=[PersonOrOrganization('Example Repository')],
        production_year='2026',
        subject_areas=[SubjectArea('Chemistry')],
        resource=Resource('Research data', 'Dataset'),
        geo_locations=[GeoLocation(region='Berlin')],
        rights=Rights('CC BY 4.0 Attribution'),
        rights_holders=[PersonOrOrganization('Example University')],
    )

    payload = to_xml_payload(metadata)
    xml = RadarExportRenderer().render(payload)

    assert missing_required_fields(metadata) == ()
    assert validate_radar_xml(xml) is None


def test_import_uses_public_lookup_methods():
    radar_import = make_import('''
        <radar:radarDataset
            xmlns:radar="http://radar-service.eu/schemas/descriptive/radar/v09/radar-dataset"
            xmlns:re="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <re:identifier identifierType="DOI">10.1234/example</re:identifier>
          <re:title>Dataset title</re:title>
          <re:descriptions><re:description descriptionType="Abstract">Description</re:description></re:descriptions>
          <re:keywords><re:keyword>FAIR</re:keyword></re:keywords>
          <re:resource resourceType="Dataset">Research data</re:resource>
          <re:dataSources><re:dataSource dataSourceDetail="Observation">Survey data</re:dataSource></re:dataSources>
          <re:fundingReferences><re:fundingReference>
            <re:funderName>Example Funder</re:funderName>
            <re:awardNumber>ABC-123</re:awardNumber>
          </re:fundingReference></re:fundingReferences>
          <re:version>2.1</re:version>
        </radar:radarDataset>
    ''')

    radar_import.process()

    paths = {value.attribute.path for value in radar_import.values}
    option_paths = {value.option.uri_path for value in radar_import.values if value.option}
    assert 'project/dataset/data_publication_pid' in paths
    assert 'project/dataset/description' in paths
    assert 'project/dataset/format' not in paths
    assert 'project/dataset/creation_methods' in paths
    assert 'project/funder/grant_nr' in paths
    assert 'resource_type_general/dataset' not in option_paths
    assert 'project/dataset/version' not in paths
    assert {issue.field for issue in radar_import.mapping_issues} >= {
        'descriptions', 'version', 'resource.resourceType',
    }


def test_project_level_imports_are_deduplicated_across_datasets(db):
    radar_import = make_import('''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <title>Dataset title</title>
          <keywords><keyword>FAIR</keyword></keywords>
          <contributors><contributor contributorType="Other">
            <contributorName>Doe, Jane</contributorName>
            <givenName>Jane</givenName><familyName>Doe</familyName>
            <nameIdentifier nameIdentifierScheme="ORCID">0000-0001</nameIdentifier>
          </contributor></contributors>
          <fundingReferences><fundingReference>
            <funderName>Example Funder</funderName><awardNumber>ABC-123</awardNumber>
          </fundingReference></fundingReferences>
        </radarDataset>
    ''')

    radar_import.process()
    radar_import.process()

    global_values = [value for value in radar_import.values if value.attribute.path in {
        'project/research_question/keywords', 'project/partner/name', 'project/funder/name'
    }]
    assert [(value.attribute.path, value.text) for value in global_values] == [
        ('project/research_question/keywords', 'FAIR'),
        ('project/partner/name', 'Doe, Jane'),
        ('project/funder/name', 'Example Funder'),
    ]


def test_api_vocabulary_is_derived_from_xml_vocabulary():
    metadata = RadarMetadata(
        related_identifiers=[Identifier('id', 'RAiD', 'IsTranslationOf')],
    )

    api = to_api_payload(metadata)

    assert XMLVocabulary.related_identifier_type_options['identifier_type/raid'] == 'RAiD'
    assert api['relatedIdentifiers']['relatedIdentifier'][0] == {
        'value': 'id',
        'relatedIdentifierType': 'RAID',
        'relationType': 'IS_TRANSLATION_OF',
    }


@pytest.fixture
def staff_project(db):
    return make_data_management_project()


@pytest.mark.parametrize(
    'answers,expected,issues',
    [
        (['Dataset'], 'Dataset', False),
        (['Dataset', 'Dataset'], 'Dataset', False),
        (['Other'], 'Other', False),
        ([], None, False),
        (['dataset'], None, True),
        (['Unknown'], None, True),
        (['Dataset', 'Software'], None, True),
    ],
)
def test_resource_type_accepts_only_unambiguous_canonical_values(answers, expected, issues):
    description = Value(attribute=Attribute(path='description'), text='Data description')
    types = [Value(attribute=Attribute(path='kind'), text=text, collection_index=i) for i, text in enumerate(answers)]
    context = ProjectReadContext({'description': [description], 'kind': types}, {}, provenance=[])
    result = read_resource(
        context,
        source=Source('description'),
        type_source=Source('kind'),
        option_map=XMLVocabulary.resource_type_general_options,
        target='resource',
    )
    assert result == Resource('Data description', expected)
    assert bool(context.issues) is issues


def test_resource_type_requires_description_and_never_reads_unconfigured_sources():
    kind = Value(attribute=Attribute(path='kind'), text='Dataset')
    context = ProjectReadContext({'kind': [kind]}, {}, provenance=[])
    assert (
        read_resource(
            context,
            source=Source('description'),
            type_source=Source('kind'),
            option_map=XMLVocabulary.resource_type_general_options,
            target='resource',
        )
        is None
    )
    assert any(a.outcome == 'skipped' and a.sources[0].value is kind for a in context.provenance)
    description = Value(attribute=Attribute(path='description'), text='Data')
    context = ProjectReadContext({'kind': [kind], 'description': [description]}, {}, provenance=[])
    assert read_resource(context, source=Source('description'), target='resource') == Resource('Data')
    assert all(s.value is not kind for a in context.provenance for s in a.sources)


def test_resource_options_follow_dataset_scope_and_reach_both_exports(staff_project):
    option = Option.objects.create(uri_prefix='https://custom.test', uri_path='type', text_lang1='Not a type label')
    add_answer(staff_project, 'custom/type', '', option=option, set_index=1)
    profile = make_tf_mapping(
        resource=partial(
            read_resource,
            source=Source('project/dataset/description'),
            type_source=Source('custom/type'),
            option_map={option.uri: 'Dataset'},
        )
    )
    service = build_export_service(staff_project, profile=profile, collect_mapping=True)
    first = service.mapping(service.reader(1)).metadata
    tenth = service.mapping(service.reader(10)).metadata
    assert first.resource == Resource('Data', 'Dataset')
    assert tenth.resource == Resource('Data')
    assert to_api_payload(first)['resource']['resourceType'] == 'DATASET'
    xml = build_xml_export_service(staff_project, profile=profile).compute_files([1])[0].xml_data
    assert b'resourceType="Dataset"' in xml


@pytest.mark.parametrize(
    'scheme,raw,expected',
    [
        ('DOI', '10.1234/example', '10.1234/example'),
        ('DOI', ' https://doi.org/10.1234/example ', '10.1234/example'),
        ('DOI', 'http://dx.doi.org/10.1234/example', '10.1234/example'),
        ('DOI', 'https://DOI.ORG:443/10.1234/a%2Bb', '10.1234/a+b'),
        ('Handle', 'https://hdl.handle.net/1234/example', '1234/example'),
        ('Handle', '1234/example', '1234/example'),
        ('RADAR', '12/34', '12/34'),
        ('DOI', 'not-a-pid', None),
        ('DOI', '10.1234/a/b', None),
        ('DOI', '10.1234/with spaces', None),
        ('DOI', '<b>10.1234/example</b>', None),
        ('DOI', 'https://example.test/10.1234/example', None),
        ('DOI', 'https://hdl.handle.net/1234/example', None),
        ('DOI', 'https://doi.org/10.1234/example?query=x', None),
        ('DOI', 'https://doi.org/10.1234/example#fragment', None),
        ('DOI', 'https://user@doi.org/10.1234/example', None),
        ('DOI', 'https://doi.org:invalid/10.1234/example', None),
        ('DOI', 'https://doi.org/10.1234/a%2Fb', None),
        ('DOI', 'https://doi.org/10.1234/a%20b', None),
        ('DOI', 'https://doi.org/10.1234/%FF', None),
        ('DOI', 'https://doi.org/10.1234/%00', None),
        ('DOI', 'https://doi.org/10.1234/ex\nample', None),
        ('URL', '12/34', None),
    ],
)
def test_primary_identifier_normalization_and_schema_shape(scheme, raw, expected):
    assert normalize_primary_identifier(raw, scheme) == expected
    if expected:
        kind = get_radar_schema().maps.types[
            '{http://radar-service.eu/schemas/descriptive/radar/v09/radar-types}identifierValue'
        ]
        assert kind.is_valid(expected)


@pytest.mark.parametrize('raw,expected', [('https://doi.org/10.1234/example', '10.1234/example'), ('not-a-pid', None)])
def test_tf_primary_identifier_payload_and_provenance(raw, expected):
    path, scheme_path = 'project/dataset/data_publication_pid', 'project/dataset/pids/system'
    answer = Value(attribute=Attribute(path=path), text=raw)
    scheme = Value(
        attribute=Attribute(path=scheme_path),
        option=Option(pk=1, uri='https://dmp.service.base4nfdi.de/terms/options/pid03', uri_path='pid03'),
    )
    context = ProjectReadContext({path: [answer], scheme_path: [scheme]}, {}, provenance=[])
    identifier = read_identifier(context, target='identifier')
    if expected:
        assert identifier.value == expected
        assert not context.issues
        metadata = complete_metadata(identifier=identifier)
        assert to_api_payload(metadata)['identifier']['value'] == expected
        assert get_radar_validation_errors(RadarExportRenderer().render(to_xml_payload(metadata))) == ()
        assert any(a.value == expected and a.sources[0].value is answer for a in context.provenance)
    else:
        assert identifier is None
        assert 'identifier' not in to_api_payload(complete_metadata(identifier=identifier))
        assert context.issues
        assert any(a.outcome == 'rejected' and a.sources[0].value is answer for a in context.provenance)
