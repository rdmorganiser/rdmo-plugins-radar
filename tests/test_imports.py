from types import SimpleNamespace
from unittest.mock import Mock, patch
from xml.etree import ElementTree

import pytest

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot, Value

from rdmo_radar.imports import RadarImport
from rdmo_radar.metadata.funding import merge_funding
from rdmo_radar.metadata.importer import write_metadata
from rdmo_radar.metadata.people import write_creators
from rdmo_radar.metadata.template_framework import DEFAULT_URI_PREFIX
from rdmo_radar.metadata.types import FundingReference, Identifier, PersonOrOrganization, RadarMetadata
from rdmo_radar.metadata.write_context import ProjectWriteContext
from rdmo_radar.metadata.xml import parse_xml

from .helpers import add_answer, add_attribute, add_namespaced_attribute


def make_context(existing=None, staged=None):
    existing = existing or []
    paths = {
        'project/funder/id',
        'project/funder/name',
        'project/funder/grant_nr',
        'project/funder/programme/url',
        'project/funder/programme/title',
        'project/funder/name_identifier',
        'project/research_question/keywords',
        'project/dataset/creator/name',
        'project/dataset/creator/name_type',
    }
    attributes = {Attribute.build_uri(DEFAULT_URI_PREFIX, path): Attribute(path=path) for path in paths}
    plugin = SimpleNamespace(
        values=list(staged or []),
        get_attribute=attributes.get,
        get_option=lambda uri: None,
    )
    values = {}
    for value in existing:
        values.setdefault(value.attribute.path, []).append(value)
    return ProjectWriteContext(plugin, dataset_index=0, existing_values=values)


def test_funder_identifier_uses_rddm_type_attribute():
    root = ElementTree.fromstring('''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <fundingReferences><fundingReference>
            <funderName>Example Funder</funderName>
            <funderIdentifier type="ROR">https://ror.org/123</funderIdentifier>
          </fundingReference></fundingReferences>
        </radarDataset>
    ''')

    reference = parse_xml(root).funding_references[0]

    assert reference.funder_identifier == Identifier('https://ror.org/123', 'ROR')


def test_funder_identifier_is_reported_instead_of_written_to_set_marker():
    context = make_context()
    reference = FundingReference(
        funder_name='Example Funder',
        funder_identifier=Identifier('https://ror.org/123', 'ROR'),
    )

    merge_funding(context, [reference])

    marker = next(value for value in context.import_plugin.values if value.attribute.path == 'project/funder/id')
    assert marker.text == 'Example Funder'
    assert not any(value.attribute.path == 'project/funder/name_identifier' for value in context.import_plugin.values)
    assert context.issues[0].field == 'funderIdentifier'


def test_conflicting_existing_funding_value_is_preserved_with_warning():
    context = make_context()
    merge_funding(context, [FundingReference(funder_name='Example Funder', award_number='ABC-123')])
    merge_funding(context, [FundingReference(funder_name='Example Funder', award_number='DIFFERENT')])

    awards = [
        value.text for value in context.import_plugin.values
        if value.attribute.path == 'project/funder/grant_nr'
    ]
    assert awards == ['ABC-123']
    assert any(issue.field == 'project/funder/grant_nr' for issue in context.issues)


def test_merge_uses_existing_and_staged_values_without_changing_prepared_data(db, django_assert_num_queries):
    path = 'project/research_question/keywords'
    existing = Value(attribute=Attribute(path=path), text=' FAIR ', collection_index=4)
    staged = Value(attribute=existing.attribute, text='Open data', collection_index=7)
    context = make_context(existing=[existing], staged=[staged])

    with django_assert_num_queries(0):
        assert context.add_unique_text(path, 'fair') is None
        assert context.add_unique_text(path, ' OPEN   DATA ') is None
        added = context.add_unique_text(path, 'Reproducibility')
        assert context.get_values(path) == [existing, staged, added]

    assert added.collection_index == 8
    assert added.set_index == 0
    assert added.pk is None
    assert context.existing_values[path] == [existing]
    assert context.import_plugin.values == [staged, added]


def test_staged_text_and_options_keep_creator_coordinates(db, django_assert_num_queries):
    context = make_context()
    context.dataset_index = 10
    option = Option(uri_path='name_type/personal')
    context.import_plugin.get_option = lambda uri: option if uri == Option.build_uri(
        DEFAULT_URI_PREFIX, option.uri_path,
    ) else None

    with django_assert_num_queries(0):
        write_creators(context, [
            PersonOrOrganization('First', name_type='Personal'),
            PersonOrOrganization('Second', name_type='Personal'),
        ])

    assert [(value.attribute.path, value.text, value.option, value.set_prefix, value.set_index,
             value.collection_index, value.pk) for value in context.import_plugin.values] == [
        ('project/dataset/creator/name', 'First', None, '10', 0, 0, None),
        ('project/dataset/creator/name_type', None, option, '10', 0, 0, None),
        ('project/dataset/creator/name', 'Second', None, '10', 1, 0, None),
        ('project/dataset/creator/name_type', None, option, '10', 1, 0, None),
    ]
    with django_assert_num_queries(0):
        value = context.add_option('project/dataset/creator/name_type', 'Personal',
                                   {'name_type/personal': 'Personal'}, text='Details',
                                   collection_index=3, dataset=False)
    assert (value.text, value.option, value.set_prefix, value.set_index, value.collection_index, value.pk) == (
        'Details', option, '', 0, 3, None,
    )
    assert context.get_values('project/dataset/creator/name_type')[-1] is value


@pytest.mark.parametrize('group_count', [1, 50, 100])
def test_import_loads_values_once_and_preserves_project_data(db, django_assert_num_queries, group_count):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Existing dataset', set_index=3)
    # Preserve the established title-only allocation rule, excluding snapshots.
    add_answer(project, 'project/dataset/id', 'Marker', set_index=50)
    snapshot = Snapshot.objects.create(project=project, title='Earlier')
    add_answer(project, 'project/dataset/title', 'Old snapshot', set_index=99, snapshot=snapshot)
    add_answer(project, 'project/research_question/keywords', ' FAIR ', collection_index=4)
    add_answer(project, 'project/partner/name', 'Existing Partner', set_index=5)
    add_answer(project, 'project/partner/given_name', 'Jane', set_index=5)
    add_answer(project, 'project/funder/id', 'Existing Funder', set_index=7)
    add_answer(project, 'project/funder/name', 'Existing Funder', set_index=7)
    add_answer(project, 'project/funder/grant_nr', 'Keep award', set_index=7)
    for path in ('project/partner/family_name', 'project/funder/programme/title', 'project/funder/programme/url'):
        add_attribute(path)
    persisted = list(project.values.values())
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = project
    contributors = ''.join(
        f'<contributor><contributorName>Partner {index}</contributorName></contributor>'
        for index in range(group_count)
    )
    funders = ''.join(
        f'<fundingReference><funderName>Funder {index}</funderName>'
        f'<awardNumber>Award {index}</awardNumber></fundingReference>'
        for index in range(group_count)
    )
    plugin.root = ElementTree.fromstring(f'''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <title>Imported dataset</title>
          <keywords><keyword>fair</keyword><keyword>New keyword</keyword><keyword> NEW KEYWORD </keyword></keywords>
          <contributors>
            <contributor><contributorName>Existing Partner</contributorName>
              <givenName>Changed</givenName></contributor>
            {contributors}{contributors}
          </contributors>
          <fundingReferences>
            <fundingReference><funderName>Existing Funder</funderName>
              <awardNumber>Different</awardNumber></fundingReference>
            {funders}{funders}
          </fundingReferences>
        </radarDataset>
    ''')

    with django_assert_num_queries(1):
        plugin.process()

    assert list(project.values.values()) == persisted
    assert all(value.pk is None and value.project_id is None and value.snapshot_id is None for value in plugin.values)
    assert [(value.text, value.set_index) for value in plugin.values
            if value.attribute.path == 'project/dataset/title'] == [('Imported dataset', 4)]
    assert [(value.text, value.collection_index) for value in plugin.values
            if value.attribute.path == 'project/research_question/keywords'] == [('New keyword', 5)]
    assert [(value.text, value.set_index) for value in plugin.values
            if value.attribute.path == 'project/partner/name'] == [
        (f'Partner {index}', 6 + index) for index in range(group_count)
    ]
    assert [(value.text, value.set_index) for value in plugin.values
            if value.attribute.path == 'project/funder/grant_nr'] == [
        (f'Award {index}', 8 + index) for index in range(group_count)
    ]
    assert {issue.field for issue in plugin.mapping_issues} == {
        'project/partner/given_name', 'project/funder/grant_nr',
    }


def test_write_metadata_loads_once_for_direct_callers(db, django_assert_num_queries):
    project = Project.objects.create(title='Project')
    add_attribute('project/dataset/title')
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = project

    with django_assert_num_queries(1):
        assert write_metadata(plugin, RadarMetadata(title='First'), 0) == ()
    with django_assert_num_queries(0):
        assert write_metadata(plugin, RadarMetadata(title='Second'), 1, existing_values={}) == ()

    assert [(value.text, value.set_index, value.pk) for value in plugin.values] == [
        ('First', 0, None), ('Second', 1, None),
    ]


def test_import_requires_an_existing_project():
    from django.core.exceptions import ValidationError

    plugin = RadarImport.__new__(RadarImport)
    plugin.current_project = None
    with pytest.raises(ValidationError, match='existing projects'):
        plugin.process()


def test_lookup_precedence_and_operation_caches(db, django_assert_num_queries):
    attribute = add_attribute('project/dataset/creator/name')
    custom_attribute = add_attribute('project/dataset/creator/name_type')
    custom_attribute.uri_prefix = 'https://custom.example.test/terms'
    custom_attribute.save()
    option_path = 'name_type/personal'
    options = [Option.objects.create(uri_prefix=prefix, uri_path=option_path)
               for prefix in (DEFAULT_URI_PREFIX, 'https://custom.example.test/terms/')]
    custom_option = Option.objects.create(uri_prefix='https://custom.example.test/terms', uri_path='custom/type')
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.get_attribute = Mock(wraps=plugin.get_attribute)
    plugin.get_option = Mock(wraps=plugin.get_option)
    context = ProjectWriteContext(plugin, 0, existing_values={})

    with django_assert_num_queries(0):
        assert context.fetch_attribute(attribute.path) == attribute
        assert context.fetch_option(option_path) == options[0]
    with django_assert_num_queries(1):
        assert context.fetch_attribute(custom_attribute.path) == custom_attribute
    with django_assert_num_queries(1):
        assert context.fetch_option(custom_option.uri_path) == custom_option
    with django_assert_num_queries(1):
        assert context.fetch_attribute('missing') is None
    with django_assert_num_queries(1):
        assert context.fetch_option('missing') is None
    calls = (plugin.get_attribute.call_count, plugin.get_option.call_count)
    with django_assert_num_queries(0):
        for path in (attribute.path, custom_attribute.path, 'missing'):
            context.fetch_attribute(path)
        for path in (option_path, custom_option.uri_path, 'missing'):
            context.fetch_option(path)
    assert (plugin.get_attribute.call_count, plugin.get_option.call_count) == calls
    assert plugin.get_attribute.call_args_list[0].args == (Attribute.build_uri(DEFAULT_URI_PREFIX, attribute.path),)

    # A later operation sees new objects and the remaining unique custom-namespace Option.
    new_attribute = add_attribute('missing')
    new_option = Option.objects.create(uri_prefix='https://rdmorganiser.github.io/terms', uri_path='missing')
    Option.objects.filter(pk=options[0].pk).delete()
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    context = ProjectWriteContext(plugin, 0, existing_values={})
    with django_assert_num_queries(1):
        assert context.fetch_option(option_path) == options[1]
        assert context.fetch_attribute('missing') == new_attribute
        assert context.fetch_option('missing') == new_option


def test_short_import_paths_use_model_builders_and_the_official_default(db, settings, django_assert_num_queries):
    settings.DEFAULT_URI_PREFIX = 'https://installation.example.test/terms/'
    attribute = add_attribute('research/type')
    add_namespaced_attribute(attribute.path, settings.DEFAULT_URI_PREFIX)
    option = Option.objects.create(uri_prefix=DEFAULT_URI_PREFIX, uri_path='type/example')
    Option.objects.create(uri_prefix=settings.DEFAULT_URI_PREFIX, uri_path=option.uri_path)
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.get_attribute = Mock(wraps=plugin.get_attribute)
    plugin.get_option = Mock(wraps=plugin.get_option)
    context = ProjectWriteContext(plugin, 0, {})

    with (
        patch.object(Attribute, 'build_uri', wraps=Attribute.build_uri) as build_attribute_uri,
        patch.object(Option, 'build_uri', wraps=Option.build_uri) as build_option_uri,
        django_assert_num_queries(0),
    ):
        assert context.fetch_attribute(attribute.path) == attribute
        assert context.fetch_option(option.uri_path) == option
        assert context.fetch_attribute(attribute.path) == attribute
        assert context.fetch_option(option.uri_path) == option

    build_attribute_uri.assert_called_once_with(DEFAULT_URI_PREFIX, attribute.path)
    build_option_uri.assert_called_once_with(DEFAULT_URI_PREFIX, option.uri_path)
    plugin.get_attribute.assert_called_once_with(attribute.uri)
    plugin.get_option.assert_called_once_with(option.uri)
    assert attribute.uri == 'https://rdmorganiser.github.io/terms/domain/research/type'
    assert option.uri == 'https://rdmorganiser.github.io/terms/options/type/example'


@pytest.mark.parametrize('method_name', ('fetch_attribute', 'fetch_option'))
def test_empty_import_paths_return_none_without_queries_or_uri_construction(db, django_assert_num_queries, method_name):
    plugin = SimpleNamespace(values=[], get_attribute=Mock(), get_option=Mock())
    context = ProjectWriteContext(plugin, 0, {})
    with django_assert_num_queries(0):
        assert getattr(context, method_name)('') is None
        assert getattr(context, method_name)('') is None
    plugin.get_attribute.assert_not_called()
    plugin.get_option.assert_not_called()
    assert plugin.values == []


def test_unmapped_options_and_missing_fields_warn_without_staging(db, django_assert_num_queries):
    context = make_context()
    with django_assert_num_queries(2):
        assert context.add('missing', 'Text') is None
        assert context.add_option('missing', 'Personal', {'name_type/personal': 'Personal'}) is None
    with django_assert_num_queries(0):
        assert context.add_option('project/dataset/creator/name_type', 'Personal',
                                  {'name_type/personal': 'Personal'}) is None
        assert context.add_option('project/dataset/creator/name_type', 'Unknown',
                                  {'name_type/personal': 'Personal'}) is None
    assert context.import_plugin.values == []
    assert [issue.reason for issue in context.issues] == [
        'RDMO Attribute is not installed', 'RDMO Attribute is not installed',
        'RDMO Option is not installed: name_type/personal', 'RADAR controlled value has no RDMO mapping',
    ]


def test_ambiguous_custom_attribute_fallback_is_cached_and_stages_nothing(db, django_assert_num_queries):
    path = 'research/title'
    for namespace in ('first', 'second'):
        add_namespaced_attribute(path, f'https://{namespace}.test')
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.get_attribute = Mock(wraps=plugin.get_attribute)
    context = ProjectWriteContext(plugin, 0, {})
    with django_assert_num_queries(1):
        assert context.add(path, 'First') is None
    calls = plugin.get_attribute.call_count
    with django_assert_num_queries(0):
        assert context.add(path, 'Second') is None
        assert context.fetch_attribute(path) is None
    assert plugin.get_attribute.call_count == calls
    assert plugin.values == []
    assert [issue.reason for issue in context.issues] == ['Ambiguous Attribute import destination']


def test_ambiguous_custom_option_fallback_is_cached_and_stages_nothing(db, django_assert_num_queries):
    path = 'research/type'
    add_attribute(path)
    for namespace in ('first', 'second'):
        Option.objects.create(uri_prefix=f'https://{namespace}.test', uri_path='type/example')
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.get_option = Mock(wraps=plugin.get_option)
    context = ProjectWriteContext(plugin, 0, {})
    with django_assert_num_queries(1):
        assert context.add_option(path, 'Example', {'type/example': 'Example'}) is None
    calls = plugin.get_option.call_count
    with django_assert_num_queries(0):
        assert context.add_option(path, 'Example', {'type/example': 'Example'}) is None
    assert plugin.get_option.call_count == calls
    assert plugin.values == []
    assert [issue.reason for issue in context.issues] == ['Ambiguous Option import destination']


def test_exact_import_uris_override_legacy_prefixes_without_fallback(db, django_assert_num_queries):
    path = 'research/type'
    add_attribute(path)
    attribute = add_namespaced_attribute(path, 'https://custom.test')
    Option.objects.create(uri_prefix='https://rdmorganiser.github.io/terms', uri_path='type/example')
    option = Option.objects.create(uri_prefix='https://custom.test', uri_path='type/example')
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    context = ProjectWriteContext(plugin, 10, {})
    with django_assert_num_queries(0):
        value = context.add_option(attribute.uri, 'Example', {option.uri: 'Example'}, text='Details')
        assert context.get_values(attribute.uri) == [value]
        assert context.get_values(path) == []
        assert context.fetch_attribute('https://absent.test/domain/research/type') is None
        assert context.fetch_option('https://absent.test/options/type/example') is None
    assert (value.attribute_id, value.option_id, value.set_index, value.pk) == (attribute.pk, option.pk, 10, None)
    assert context.issues == []


def test_import_merging_and_allocation_ignore_other_attribute_namespaces(db, django_assert_num_queries):
    path = 'research/keywords'
    canonical = add_attribute(path)
    other = add_namespaced_attribute(path, 'https://other.test')
    existing = Value(attribute=canonical, text='Keep', collection_index=2)
    foreign = Value(attribute=other, text='New', collection_index=99)
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    context = ProjectWriteContext(plugin, 0, {path: [existing, foreign]})
    with django_assert_num_queries(0):
        value = context.add_unique_text(path, 'New')
        assert value is not None
        assert value.collection_index == 3
        assert value.attribute_id == canonical.pk
        assert context.get_values(path) == [existing, value]
        assert context.get_values(other.uri) == [foreign]
        assert context.compute_next_set_index(path) == 1
    assert context.existing_values[path] == [existing, foreign]
    assert context.issues == []


def test_template_framework_import_allocates_only_after_selected_title_namespace(db):
    from rdmo_radar.factories import build_import_service

    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Canonical', set_index=2)
    other = add_namespaced_attribute('project/dataset/title', 'https://other.test')
    Value.objects.create(project=project, attribute=other, text='Foreign', set_index=99)
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = project
    service = build_import_service(plugin, parser=lambda root: root)
    assert service.process(RadarMetadata(title='Imported')) == ()
    assert len(plugin.values) == 1
    assert plugin.values[0].attribute.uri == Attribute.build_uri(DEFAULT_URI_PREFIX, 'project/dataset/title')
    assert plugin.values[0].set_index == 3


def test_ambiguous_fallback_does_not_merge_existing_foreign_answers(db):
    path = 'research/keywords'
    attributes = [add_namespaced_attribute(path, f'https://{namespace}.test') for namespace in ('first', 'second')]
    values = [Value(attribute=attribute, text='Existing') for attribute in attributes]
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    context = ProjectWriteContext(plugin, 0, {path: values})
    assert context.add_unique_text(path, 'Existing') is None
    assert plugin.values == []
    assert [issue.reason for issue in context.issues] == ['Ambiguous Attribute import destination']


def test_default_import_reuses_custom_destination_resolution_for_allocation_and_staging(db, django_assert_num_queries):
    from rdmo_radar.factories import build_import_service

    project = Project.objects.create(title='Project')
    attribute = add_namespaced_attribute('project/dataset/title', 'https://custom.test')
    Value.objects.create(project=project, attribute=attribute, text='Existing', set_index=3)
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = project
    with django_assert_num_queries(2):
        service = build_import_service(plugin, parser=lambda root: root)
    with django_assert_num_queries(0):
        assert service.process(RadarMetadata(title='Imported')) == ()
    assert len(plugin.values) == 1
    assert (plugin.values[0].attribute_id, plugin.values[0].set_index) == (attribute.pk, 4)


def test_ambiguous_title_allocation_retains_diagnostics_and_stages_nothing(db, django_assert_num_queries):
    from rdmo_radar.factories import build_import_service

    project = Project.objects.create(title='Project')
    for index, namespace in enumerate(('first', 'second')):
        attribute = add_namespaced_attribute('project/dataset/title', f'https://{namespace}.test')
        Value.objects.create(project=project, attribute=attribute, text='Existing', set_index=index)
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = project
    with django_assert_num_queries(2):
        service = build_import_service(plugin, parser=lambda root: root)
    with django_assert_num_queries(0):
        issues = service.process(RadarMetadata(title='Imported'))
    assert [issue.reason for issue in issues] == ['Ambiguous Attribute import destination']
    assert plugin.values == []


def test_distinct_uri_less_staged_attributes_are_not_combined():
    path = 'research/title'
    attributes = [Attribute(path=path), Attribute(path=path)]
    staged = [Value(attribute=attribute, text='Existing') for attribute in attributes]
    plugin = SimpleNamespace(values=staged, get_attribute=lambda uri: attributes[0], get_option=lambda uri: None)
    context = ProjectWriteContext(plugin, 0, {})
    assert context.get_values(path) == []
    assert context.add(path, 'New') is None
    assert plugin.values == staged
    assert [issue.reason for issue in context.issues] == ['Ambiguous synthetic Attribute import destination']


def test_subject_import_does_not_deduplicate_options_from_another_namespace(db):
    from rdmo_radar.metadata.constants import XMLVocabulary
    from rdmo_radar.metadata.dataset import write_dataset_fields
    from rdmo_radar.metadata.types import SubjectArea

    attribute = add_attribute('project/research_field/title')
    path = next(path for path, name in XMLVocabulary.controlled_subject_area_options.items() if name == 'Chemistry')
    canonical = Option.objects.create(uri_prefix='https://rdmorganiser.github.io/terms', uri_path=path)
    other = Option.objects.create(uri_prefix='https://other.test', uri_path=path)
    existing = Value(attribute=attribute, option=other)
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    context = ProjectWriteContext(plugin, 0, {attribute.path: [existing]})
    write_dataset_fields(context, RadarMetadata(subject_areas=[SubjectArea('Chemistry')]))
    assert len(plugin.values) == 1
    assert plugin.values[0].option_id == canonical.pk
    assert plugin.values[0].collection_index == 1
    assert context.issues == []


def test_import_merging_uses_primary_key_when_cached_attribute_labels_differ():
    path = 'research/title'
    current = Attribute(pk=17, path=path, uri='https://current.test/domain/research/title')
    cached = Attribute(pk=17, path=path, uri=Attribute.build_uri(DEFAULT_URI_PREFIX, path))
    existing = Value(attribute=current, text='Existing', collection_index=2)
    staged = Value(attribute=cached, text='Staged', collection_index=4)
    plugin = SimpleNamespace(values=[staged], get_attribute=lambda uri: cached, get_option=lambda uri: None)
    context = ProjectWriteContext(plugin, 0, {path: [existing]})
    assert context.add_unique_text(path, 'existing') is None
    added = context.add_unique_text(path, 'New')
    assert added.collection_index == 5
    assert added.attribute_id == 17
    assert context.get_values(path) == [existing, staged, added]
    assert context.issues == []
