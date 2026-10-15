"""Built-in profiles and a third-party mapping exercised through native registration."""
from dataclasses import replace
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from django.core.exceptions import ValidationError
from django.db import transaction

from rdmo.core.plugins import get_plugins
from rdmo.domain.models import Attribute
from rdmo.projects.models import Project, Snapshot, Value
from rdmo.questions.models import Catalog, CatalogSection, Page, PageQuestion, Question, Section, SectionPage

from rdmo_radar.exceptions import ExportStoreError, UnsupportedImportMapping
from rdmo_radar.exports import RadarProjectCredentialsExportProvider, RadarProjectExport, RadarProjectExportProvider
from rdmo_radar.factories import build_export_service, build_import_service, build_xml_export_service
from rdmo_radar.imports import RadarImport
from rdmo_radar.mappings import ExportDataset, validate_datasets
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING
from rdmo_radar.metadata.types import Description, MappingResult, RadarMetadata
from rdmo_radar.metadata.values import coordinates
from rdmo_radar.metadata.write_context import ProjectWriteContext

from .helpers import add_answer, add_attribute, add_namespaced_attribute, export_for

CUSTOM_TITLE = 'https://custom.test/domain/research/title'
CUSTOM_URL = 'https://custom.test/domain/research/radar_url'
CUSTOM_ID = 'https://custom.test/domain/research/radar_id'


def read_metadata(context):
    """The README example: field mapping needs no custom discovery or reader."""
    description = context.get_text('https://example.org/terms/domain/research/description')
    return MappingResult(
        RadarMetadata(
            title=context.get_text('https://example.org/terms/domain/research/title') or context.project.title,
            descriptions=[Description(description)] if description else [],
            keywords=context.get_texts('https://example.org/terms/domain/research/keywords'),
        ),
        tuple(context.issues),
    )


class ExampleRadarExport(RadarProjectExport):
    mapping = replace(PROJECT_MAPPING, compute_metadata=read_metadata)


@pytest.mark.parametrize('provider_class', [RadarProjectExportProvider, RadarProjectCredentialsExportProvider])
def test_direct_payload_reads_prepared_custom_attributes_without_metadata_mapping(
    example_project, django_assert_num_queries, provider_class,
):
    class ExampleRadarExportProvider(provider_class):
        def get_payload(self, dataset):
            context = self.get_context(dataset)
            return {
                'technicalMetadata': {
                    'retentionPeriod': 3,
                    'archiveDate': 1234,
                    'publishDate': 4321,
                    'responsibleEmail': self.request.user.email,
                    'schema': {'key': 'RDDM', 'version': '9.3'},
                },
                'descriptiveMetadata': {
                    'title': context.get_text('https://example.org/terms/domain/research/title'),
                    'keywords': {'keyword': [
                        {'value': keyword}
                        for keyword in context.get_texts('https://example.org/terms/domain/research/keywords')
                    ]},
                },
            }

    provider = export_for(example_project, ExampleRadarExportProvider)
    dataset = provider.get_datasets()[0]
    service = provider.get_service()
    service.mapping = Mock(side_effect=AssertionError('Canonical mapping used for a custom request'))
    service.serializer = Mock(side_effect=AssertionError('Canonical serializer used for a custom request'))
    with django_assert_num_queries(0):
        assert provider.get_payload(dataset) == {
            'technicalMetadata': {
                'retentionPeriod': 3, 'archiveDate': 1234, 'publishDate': 4321,
                'responsibleEmail': 'user@example.test', 'schema': {'key': 'RDDM', 'version': '9.3'},
            },
            'descriptiveMetadata': {
                'title': 'Measurements',
                'keywords': {'keyword': [{'value': 'chemistry'}, {'value': 'measurements'}]},
            },
        }
        assert provider.get_mapping_warnings() == []
    assert dataset.key == 'project'
    service.mapping.assert_not_called()
    service.serializer.assert_not_called()


@pytest.mark.parametrize('provider_class', [RadarProjectExportProvider, RadarProjectCredentialsExportProvider])
def test_payload_override_can_reuse_defaults_and_prepared_attribute_access(
    example_project, django_assert_num_queries, provider_class,
):
    class ExampleRadarExportProvider(provider_class):
        def get_payload(self, dataset):
            context = self.get_context(dataset)
            payload = super().get_payload(dataset)
            payload['descriptiveMetadata']['title'] = context.get_text(
                'https://example.org/terms/domain/research/title',
            )
            return payload

    provider = export_for(example_project, ExampleRadarExportProvider)
    dataset = provider.get_datasets()[0]
    provider.get_service().clock = lambda: 1_725_000_000.123
    with django_assert_num_queries(0):
        payload = provider.get_payload(dataset)
    assert payload == {
        'technicalMetadata': {
            'retentionPeriod': 10, 'archiveDate': 1_725_000_000_123, 'publishDate': 1_725_000_000_123,
            'responsibleEmail': 'user@example.test', 'schema': {'key': 'RDDM', 'version': '9.3'},
        },
        'descriptiveMetadata': {'title': 'Measurements'},
    }


def custom_reader(project, snapshot=None):
    read = PROJECT_MAPPING.build_reader(project, snapshot)

    def selected(dataset):
        context = read(dataset)
        if dataset is None:
            return context
        position = dataset.scope['coordinate']
        return context.group('|'.join(map(str, position[:-1])), position[-1])

    return selected


def custom_datasets(project, reader):
    # Discovery uses a project context; custom scope is interpreted only by this package.
    context = reader(None)
    return [ExportDataset(f'record-{value.set_prefix}-{value.set_index}', value.text,
                            {'coordinate': list(map(int, coordinates(value)))})
            for value in context.get_values(CUSTOM_TITLE)]


def custom_metadata(context):
    return MappingResult(RadarMetadata(title=context.get_text(CUSTOM_TITLE)), tuple(context.issues))


def custom_store(project, dataset, radar_id, radar_url):
    position = dataset.scope['coordinate']
    with transaction.atomic():
        for uri, text in ((CUSTOM_ID, radar_id), (CUSTOM_URL, radar_url)):
            Value.objects.update_or_create(project=project, attribute=Attribute.objects.get(uri=uri), snapshot=None,
                                           set_prefix='|'.join(map(str, position[:-1])), set_index=position[-1],
                                           collection_index=0, defaults={'text': text})


def custom_import_writer(plugin, *, set_index=None, existing_values, mapping=None):
    def stage(metadata):
        if mapping is not None:
            return mapping(plugin, metadata, set_index=set_index, existing_values=existing_values)
        context = ProjectWriteContext(plugin, 3 if set_index is None else set_index, existing_values)
        context.add(CUSTOM_TITLE, metadata.title, set_prefix='7')
        return tuple(context.issues)
    return stage


CUSTOM_MAPPING = replace(PROJECT_MAPPING, get_datasets=custom_datasets, build_reader=custom_reader,
                         compute_metadata=custom_metadata, store_result=custom_store,
                         build_import_writer=custom_import_writer)


class CustomXmlExport(RadarProjectExport):
    mapping = CUSTOM_MAPPING


class CustomCredentialsExportProvider(RadarProjectCredentialsExportProvider):
    mapping = CUSTOM_MAPPING


class CustomOauthExportProvider(RadarProjectExportProvider):
    mapping = CUSTOM_MAPPING


class CustomImport(RadarImport):
    mapping = CUSTOM_MAPPING


@pytest.fixture
def custom_project(db):
    project = Project.objects.create(title='Project')
    title = add_namespaced_attribute('research/title', 'https://custom.test')
    add_namespaced_attribute('research/radar_url', 'https://custom.test')
    add_namespaced_attribute('research/radar_id', 'https://custom.test')
    for parent, name in ((1, 'First record'), (10, 'Second record')):
        Value.objects.create(project=project, attribute=title, text=name, set_prefix=str(parent), set_index=3)
    return project


@pytest.fixture
def example_project(db):
    catalog = Catalog.objects.create(uri_prefix='https://example.org/terms', uri_path='example-catalog')
    section = Section.objects.create(uri_prefix='https://example.org/terms', uri_path='example-catalog/overview')
    CatalogSection.objects.create(catalog=catalog, section=section, order=0)
    page = Page.objects.create(
        uri_prefix='https://example.org/terms',
        uri_path='example-catalog/overview/metadata',
        is_collection=False,
    )
    SectionPage.objects.create(section=section, page=page, order=0)
    project = Project.objects.create(title='Research project', description='Project administration', catalog=catalog)
    for order, (key, attribute_values) in enumerate(
        (
            ('title', ['Measurements']),
            ('description', ['An abstract about the measurements.']),
            ('keywords', ['chemistry', 'measurements']),
        )
    ):
        attribute = add_namespaced_attribute(f'research/{key}', 'https://example.org/terms')
        question = Question.objects.create(
            uri_prefix='https://example.org/terms',
            uri_path=f'example-catalog/overview/metadata/{key}',
            attribute=attribute,
            widget_type='text',
            value_type='text',
            is_collection=(key == 'keywords'),
        )
        PageQuestion.objects.create(page=page, question=question, order=order)
        for collection_index, text in enumerate(attribute_values):
            Value.objects.create(project=project, attribute=attribute, text=text, collection_index=collection_index)
    return project


def test_simple_mapping_from_ordinary_catalog_through_native_registration(
    example_project,
    settings,
    django_assert_num_queries,
):
    settings.PROJECT_EXPORTS = [
        ('simple-radar', 'Simple RADAR', 'tests.test_mapping_profiles.ExampleRadarExport'),
    ]
    export = get_plugins('PROJECT_EXPORTS')['simple-radar']
    export.project = example_project
    xml_service = export.get_service()
    rest_service = build_export_service(example_project, profile=export.mapping)
    expected = RadarMetadata(
        title='Measurements',
        descriptions=[Description('An abstract about the measurements.')],
        keywords=['chemistry', 'measurements'],
    )
    with django_assert_num_queries(0):
        datasets = export.get_datasets()
        assert [dataset.key for dataset in datasets] == ['project']
        dataset = datasets[0]
        assert xml_service.mapping(xml_service.reader(dataset)) == MappingResult(expected)
        files = export.prepare_files()
        prepared = rest_service.compute_payload(dataset, 'owner@example.test')

    assert len(files) == 1
    assert files[0]['file_name'] == 'Measurements.xml'
    assert files[0]['has_warnings']
    assert 'creators.creator' in [field['path'] for field in files[0]['missing_fields']]
    assert files[0]['mapping_issues'] == prepared.issues == ()
    root = ElementTree.fromstring(files[0]['xml_data'])
    assert root.findtext('{*}title') == expected.title
    abstract = root.find('{*}descriptions/{*}description')
    assert abstract.text == expected.descriptions[0].value
    assert abstract.get('descriptionType') == 'Abstract'
    assert [keyword.text for keyword in root.findall('{*}keywords/{*}keyword')] == expected.keywords
    assert prepared.payload['descriptiveMetadata'] == {
        'title': expected.title,
        'descriptions': {'description': [{'value': expected.descriptions[0].value, 'descriptionType': 'ABSTRACT'}]},
        'keywords': {'keyword': [{'value': keyword} for keyword in expected.keywords]},
    }


def test_questions_share_attribute_values_without_duplicate_metadata(example_project, django_assert_num_queries):
    original_question = Question.objects.get(
        uri='https://example.org/terms/questions/example-catalog/overview/metadata/keywords',
    )
    shared_question = Question.objects.create(
        uri_prefix='https://example.org/terms',
        uri_path='example-catalog/overview/metadata/keywords-again',
        attribute=original_question.attribute,
        widget_type='text',
        value_type='text',
        is_collection=True,
    )
    PageQuestion.objects.create(page=original_question.pages.get(), question=shared_question, order=3)
    assert shared_question.uri != original_question.uri
    assert shared_question.attribute_id == original_question.attribute_id
    keyword_values = list(example_project.values.filter(attribute_id=original_question.attribute_id))
    assert [value.text for value in keyword_values] == ['chemistry', 'measurements']

    service = build_export_service(example_project, profile=ExampleRadarExport.mapping)
    dataset = ExampleRadarExport.mapping.get_datasets(example_project, service.reader)[0]
    context = service.reader(dataset)
    with django_assert_num_queries(0):
        assert context.get_values(original_question.attribute) == keyword_values
        assert context.get_values(shared_question.attribute) == keyword_values
        result = service.mapping(context)
        assert result.metadata.keywords == ['chemistry', 'measurements']
        assert result.issues == ()
        assert service.compute_payload(dataset, 'owner@example.test').payload['descriptiveMetadata']['keywords'] == {
            'keyword': [{'value': 'chemistry'}, {'value': 'measurements'}],
        }


@pytest.mark.parametrize('catalog', [False, True])
def test_project_profile_exports_one_conservative_record_without_datasets(db, catalog):
    project = Project.objects.create(title='Project title', description='A project description',
                                     catalog=Catalog.objects.create(uri_prefix='https://test', uri_path='catalog')
                                     if catalog else None)
    add_answer(project, 'project/dataset/title', 'Ignored dataset title')
    service = build_export_service(project, profile=PROJECT_MAPPING)
    datasets = PROJECT_MAPPING.get_datasets(project, service.reader)
    assert [dataset.key for dataset in datasets] == ['project']
    assert service.mapping(service.reader(datasets[0])) == MappingResult(RadarMetadata(title=project.title))
    assert service.compute_payload(datasets[0], 'owner@test').payload['descriptiveMetadata'] == {
        'title': 'Project title',
    }
    xml = build_xml_export_service(project, profile=PROJECT_MAPPING).compute_files(datasets)[0]
    assert xml.file_name == 'Project title.xml'
    assert 'creators.creator' in xml.missing_fields
    assert xml.has_warnings


def test_profile_modes_are_explicit_for_catalogless_and_empty_projects(db):
    project = Project.objects.create(title='Project')
    for profile, count in ((PROJECT_MAPPING, 1), (TEMPLATE_FRAMEWORK_MAPPING, 0)):
        service = build_xml_export_service(project, profile=profile)
        assert len(profile.get_datasets(project, service.reader)) == count
    for index in (0, 1, 2):
        add_answer(project, 'project/dataset/title', f'Dataset {index}', set_index=index)
    for profile, count in ((PROJECT_MAPPING, 1), (TEMPLATE_FRAMEWORK_MAPPING, 3)):
        service = build_xml_export_service(project, profile=profile)
        assert len(profile.get_datasets(project, service.reader)) == count


def test_project_profile_custom_metadata_reads_snapshot_and_reuses_preparation(db, django_assert_num_queries):
    project = Project.objects.create(title='Project')
    snapshot = Snapshot.objects.create(project=project, title='Snapshot label')
    current = add_answer(project, 'research/title', 'Live')
    add_answer(project, 'research/title', 'Saved', snapshot=snapshot)
    profile = replace(PROJECT_MAPPING, compute_metadata=lambda context: MappingResult(
        RadarMetadata(title=context.get_text(current.attribute.uri)), tuple(context.issues),
    ))
    with django_assert_num_queries(1):
        service = build_xml_export_service(project, profile=profile, snapshot=snapshot)
    dataset = profile.get_datasets(project, service.reader)[0]
    with django_assert_num_queries(0):
        assert service.mapping(service.reader(dataset)).metadata.title == 'Saved'
        assert service.mapping(service.reader(dataset)).metadata.title == 'Saved'


def test_custom_scope_keys_work_through_both_serializers_and_persistence(custom_project):
    xml = build_xml_export_service(custom_project, profile=CUSTOM_MAPPING)
    datasets = CUSTOM_MAPPING.get_datasets(custom_project, xml.reader)
    assert [dataset.key for dataset in datasets] == ['record-1-3', 'record-10-3']
    assert [file.file_name for file in xml.compute_files(datasets)] == ['First record.xml', 'Second record.xml']
    rest = build_export_service(custom_project, profile=CUSTOM_MAPPING)
    selected = datasets[1]
    assert rest.compute_payload(selected, 'owner@test').payload['descriptiveMetadata']['title'] == 'Second record'
    result = rest.store_result(selected, 'confirmed', 'https://radar.test/confirmed')
    assert result.radar_id == 'confirmed'
    assert [(value.set_prefix, value.set_index, value.text) for value in custom_project.values.filter(
        attribute__uri=CUSTOM_URL,
    )] == [('10', 3, 'https://radar.test/confirmed')]


def test_native_registration_loads_legacy_and_explicit_profiles(custom_project, settings):
    settings.PROJECT_EXPORTS = [
        ('legacy', 'Legacy', 'rdmo_radar.exports.RadarExport'),
        ('project', 'Project', 'rdmo_radar.exports.RadarProjectExport'),
        ('tf', 'TF', 'rdmo_radar.exports.RadarTemplateFrameworkExport'),
        ('custom', 'Custom', 'tests.test_mapping_profiles.CustomXmlExport'),
    ]
    plugins = get_plugins('PROJECT_EXPORTS')
    for key, count in (('legacy', 0), ('project', 1), ('tf', 0), ('custom', 2)):
        plugins[key].project = custom_project
        assert len(plugins[key].get_datasets()) == count
    assert [file['file_name'] for file in plugins['custom'].prepare_files()] == [
        'First record.xml', 'Second record.xml',
    ]


@pytest.mark.parametrize('factory', [build_export_service, build_xml_export_service])
def test_explicit_dependencies_override_profile_defaults(factory):
    reader = Mock(return_value='prepared')
    mapping = Mock(return_value=MappingResult(RadarMetadata(title='Override')))
    profile = replace(PROJECT_MAPPING, build_reader=Mock(side_effect=AssertionError('Default reader used')),
                      compute_metadata=Mock(side_effect=AssertionError('Default mapping used')))
    service = factory(None, profile=profile, reader=reader, mapping=mapping)
    dataset = ExportDataset('opaque', 'Record', {'coordinate': [1, 3]})
    assert service.mapping(service.reader(dataset)).metadata.title == 'Override'
    reader.assert_called_once_with(dataset)
    mapping.assert_called_once_with('prepared')


@pytest.mark.parametrize('profile', [None, PROJECT_MAPPING, TEMPLATE_FRAMEWORK_MAPPING])
def test_explicit_none_writer_disables_storage_without_project_queries(db, django_assert_num_queries, profile):
    service = build_export_service(None, profile=profile, reader=lambda dataset: None, writer=None)
    with django_assert_num_queries(0):
        assert service.store_result(ExportDataset('project', 'Project'), 'id', 'url').radar_url == 'url'


def test_profile_without_writer_never_borrows_template_framework_destinations(db):
    project = Project.objects.create(title='Project')
    add_attribute('project/dataset/radar_id')
    add_attribute('project/dataset/radar_url')
    service = build_export_service(project, profile=PROJECT_MAPPING)
    dataset = PROJECT_MAPPING.get_datasets(project, service.reader)[0]
    assert service.store_result(dataset, 'id', 'url').radar_url == 'url'
    assert not project.values.exists()


def test_explicit_writer_replaces_profile_storage(custom_project):
    writer = Mock()
    service = build_export_service(custom_project, profile=CUSTOM_MAPPING, writer=writer)
    dataset = ExportDataset('chosen', 'Record', {'coordinate': [10, 3]})
    service.store_result(dataset, 'id', 'url')
    writer.assert_called_once_with(dataset, 'id', 'url')
    assert not custom_project.values.filter(attribute__uri=CUSTOM_URL).exists()


def test_custom_storage_failure_preserves_confirmed_result(custom_project):
    failure = Mock(side_effect=RuntimeError('Private database detail'))
    service = build_export_service(custom_project, profile=replace(CUSTOM_MAPPING, store_result=failure))
    dataset = ExportDataset('chosen', 'Record', {'coordinate': [10, 3]})
    with pytest.raises(ExportStoreError) as caught:
        service.store_result(dataset, 'confirmed', 'https://radar.test/confirmed')
    assert caught.value.radar_id == 'confirmed'
    assert caught.value.radar_url == 'https://radar.test/confirmed'
    assert 'Private database detail' not in str(caught.value)
    failure.assert_called_once_with(custom_project, dataset, 'confirmed', 'https://radar.test/confirmed')


def test_profile_import_hook_owns_allocation_and_stages_native_values(custom_project):
    add_answer(custom_project, 'project/dataset/title', 'TF dataset', set_index=99)
    plugin = CustomImport('custom', 'Custom', 'tests.test_mapping_profiles.CustomImport')
    plugin.current_project = custom_project
    service = build_import_service(plugin, profile=CUSTOM_MAPPING, parser=lambda root: root)
    assert service.process(RadarMetadata(title='Imported record')) == ()
    assert [(value.attribute.uri, value.set_prefix, value.set_index, value.pk) for value in plugin.values] == [
        (CUSTOM_TITLE, '7', 3, None),
    ]
    assert not custom_project.values.filter(attribute__uri=CUSTOM_TITLE, text='Imported record').exists()


def test_unsupported_import_is_explicit_and_does_not_prepare_or_stage(custom_project, django_assert_num_queries):
    plugin = RadarImport('project', 'Project', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = custom_project
    with django_assert_num_queries(0), pytest.raises(UnsupportedImportMapping, match='does not support import'):
        build_import_service(plugin, profile=PROJECT_MAPPING)
    plugin.mapping = PROJECT_MAPPING
    with pytest.raises(ValidationError, match='does not support import'):
        plugin.process()
    assert plugin.values == []


def test_explicit_import_writer_overrides_unavailable_profile_without_preparation():
    writer = Mock(return_value=())
    service = build_import_service(None, profile=PROJECT_MAPPING, parser=lambda root: root, writer=writer)
    metadata = RadarMetadata(title='Explicit')
    assert service.process(metadata) == ()
    writer.assert_called_once_with(metadata)


@pytest.mark.parametrize('scope', [{'tuple': (1, 3)}, {'object': object()}, {'number': float('nan')}])
def test_dataset_scopes_must_survive_json_round_trip(scope):
    with pytest.raises((TypeError, ValueError)):
        validate_datasets([ExportDataset('record', 'Record', scope)])


def test_duplicate_dataset_keys_are_rejected():
    with pytest.raises(ValueError, match='unique'):
        validate_datasets([ExportDataset('record', 'First'), ExportDataset('record', 'Second')])


def test_third_party_discovery_reuses_prepared_values(custom_project, django_assert_num_queries):
    with django_assert_num_queries(1):
        service = build_xml_export_service(custom_project, profile=CUSTOM_MAPPING)
    with django_assert_num_queries(0):
        for _ in range(2):
            datasets = CUSTOM_MAPPING.get_datasets(custom_project, service.reader)
            assert [service.mapping(service.reader(dataset)).metadata.title for dataset in datasets] == [
                'First record', 'Second record',
            ]


@pytest.mark.parametrize('class_name, profile', [
    ('RadarExportProvider', TEMPLATE_FRAMEWORK_MAPPING),
    ('RadarCredentialsExportProvider', TEMPLATE_FRAMEWORK_MAPPING),
    ('RadarTemplateFrameworkExportProvider', TEMPLATE_FRAMEWORK_MAPPING),
    ('RadarTemplateFrameworkCredentialsExportProvider', TEMPLATE_FRAMEWORK_MAPPING),
    ('RadarProjectExportProvider', PROJECT_MAPPING),
    ('RadarProjectCredentialsExportProvider', PROJECT_MAPPING),
])
def test_registered_authentication_classes_select_profiles(custom_project, settings, class_name, profile):
    settings.PROJECT_EXPORTS = [('provider', 'RADAR', f'rdmo_radar.exports.{class_name}')]
    provider = get_plugins('PROJECT_EXPORTS')['provider']
    provider.project = custom_project
    assert provider.mapping is profile
    assert [dataset.key for dataset in provider.get_datasets()] == (
        ['project'] if profile is PROJECT_MAPPING else []
    )


def test_missing_import_hook_accepts_explicit_mapping_without_tf_allocation(custom_project):
    plugin = RadarImport('custom', 'Custom', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = custom_project
    mapping = Mock(return_value=())
    service = build_import_service(plugin, profile=PROJECT_MAPPING, mapping=mapping, parser=lambda root: root)
    metadata = RadarMetadata(title='Custom')
    assert service.process(metadata) == ()
    assert mapping.call_args.kwargs['set_index'] is None
    assert mapping.call_args.args == (plugin, metadata)
    assert plugin.values == []


def test_registered_template_framework_importer_preserves_staging(custom_project, settings):
    add_attribute('project/dataset/title')
    settings.PROJECT_IMPORTS = [('tf', 'RADAR TF', 'rdmo_radar.imports.RadarTemplateFrameworkImport')]
    plugin = get_plugins('PROJECT_IMPORTS')['tf']
    plugin.current_project = custom_project
    service = build_import_service(plugin, profile=plugin.mapping, parser=lambda root: root)
    assert service.process(RadarMetadata(title='TF dataset')) == ()
    assert [(value.attribute.path, value.set_prefix, value.set_index, value.pk) for value in plugin.values] == [
        ('project/dataset/title', '', 0, None),
    ]


def test_oauth_rejects_result_context_from_another_provider_without_storage(custom_project):
    from types import SimpleNamespace

    writer = Mock()
    provider = CustomOauthExportProvider('custom', 'Custom', 'tests.test_mapping_profiles.CustomOauthExportProvider')
    provider.mapping = replace(CUSTOM_MAPPING, store_result=writer)
    request = SimpleNamespace(session={})
    provider.store_in_session(request, 'export_context', {
        'project_id': custom_project.pk,
        'dataset': {'key': 'record-10-3', 'label': 'Record', 'scope': {'coordinate': [10, 3]}},
        'provider': 'another.package.Provider', 'persist': True,
        'radar_url': 'https://radar.test', 'language': 'en',
    })
    provider.render_export_result = Mock(return_value='confirmed link')
    assert provider.post_success(request, SimpleNamespace(json=lambda: {'id': 'confirmed'})) == 'confirmed link'
    writer.assert_not_called()
    provider.render_export_result.assert_called_once_with(
        request, 'confirmed', 'https://radar.test/radar/en/dataset/confirmed', stored=False,
    )


def test_oauth_session_stores_dataset_scope_without_reader(custom_project):
    from types import SimpleNamespace

    from rdmo_radar.exports import RadarExportProvider

    add_attribute('project/dataset/radar_id')
    add_attribute('project/dataset/radar_url')
    provider = RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarExportProvider')
    request = SimpleNamespace(session={})
    provider.store_in_session(request, 'export_context', {
        'project_id': custom_project.pk, 'provider': provider.class_name, 'persist': True,
        'radar_url': 'https://radar.test', 'language': 'en',
        'dataset': {'key': 'dataset:10|3', 'label': 'Dataset', 'scope': {'set_prefix': '10', 'set_index': 3}},
    })
    provider.get_service = Mock(side_effect=AssertionError('Reader prepared'))
    provider.render_export_result = Mock(return_value='confirmed link')
    assert provider.post_success(request, SimpleNamespace(json=lambda: {'id': 'confirmed'})) == 'confirmed link'
    stored = custom_project.values.get(attribute__path='project/dataset/radar_id')
    assert (stored.text, stored.set_prefix, stored.set_index) == ('confirmed', '10', 3)
    provider.get_service.assert_not_called()


def test_adapter_datasets_are_operation_scoped_and_rebuilt_for_profile_changes(custom_project):
    discovery = Mock(wraps=CUSTOM_MAPPING.get_datasets)
    provider = CustomXmlExport('custom', 'Custom', 'tests.test_mapping_profiles.CustomXmlExport')
    provider.project = custom_project
    provider.mapping = replace(CUSTOM_MAPPING, get_datasets=discovery)
    assert [dataset.key for dataset in provider.get_datasets()] == ['record-1-3', 'record-10-3']
    assert len(provider.get_datasets()) == 2
    discovery.assert_called_once()
    provider.mapping = PROJECT_MAPPING
    assert [dataset.key for dataset in provider.get_datasets()] == ['project']


def test_template_framework_dataset_preserves_numeric_xml_fallback_without_inventing_title(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', '', set_index=5)
    service = build_xml_export_service(project)
    dataset = TEMPLATE_FRAMEWORK_MAPPING.get_datasets(project, service.reader)[0]
    assert dataset.label == 'Dataset #6'
    file = service.compute_files([dataset])[0]
    assert file.file_name == '6.xml'
    assert 'title' in file.missing_fields
