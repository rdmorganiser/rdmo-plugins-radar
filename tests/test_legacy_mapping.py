"""Historical answer selection through the current metadata and export lifecycle."""
import json
from dataclasses import asdict, replace
from pathlib import Path
from xml.etree import ElementTree

import pytest

from rdmo.core.constants import VALUE_TYPE_DATETIME
from rdmo.core.plugins import get_plugins
from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot

from rdmo_radar.exceptions import ExportStoreError, UnsupportedImportMapping
from rdmo_radar.factories import build_export_service, build_import_service, build_xml_export_service
from rdmo_radar.mappings import validate_datasets
from rdmo_radar.mappings.legacy import LEGACY_FIELDS, LEGACY_MAPPING
from rdmo_radar.mappings.legacy.fields import first_option, first_text
from rdmo_radar.metadata.fields import Source
from rdmo_radar.metadata.provenance import pointer_value
from rdmo_radar.metadata.types import Affiliation, Identifier

from .helpers import add_answer, add_attribute, add_namespaced_attribute


@pytest.fixture
def legacy_project(db):
    fixture = json.loads((Path(__file__).parent / 'fixtures/legacy-mapping.json').read_text())
    project = Project.objects.create(title='Legacy project')
    options = {}
    for entry in fixture['answers']:
        entry = dict(entry)
        path, text = entry.pop('path'), entry.pop('text')
        if option_path := entry.pop('option', None):
            if option_path not in options:
                options[option_path] = Option.objects.create(
                    uri_prefix='https://rdmorganiser.github.io/terms', uri_path=option_path,
                    text_lang1='Other' if option_path == 'dataset_license_types/233' else option_path.rsplit('/', 1)[1],
                    additional_input=option_path == 'dataset_license_types/233',
                )
            entry['option'] = options[option_path]
        if entry.pop('date', False):
            entry['value_type'] = VALUE_TYPE_DATETIME
        add_answer(project, path, text, **entry)
    return project, fixture['expected']


def test_legacy_fixture_uses_historical_sources_with_no_mapping_queries(legacy_project, django_assert_num_queries):
    project, expected = legacy_project
    with django_assert_num_queries(1):
        service = build_export_service(project, profile=LEGACY_MAPPING, collect_mapping=True, clock=lambda: 1)
    with django_assert_num_queries(0):
        datasets = validate_datasets(LEGACY_MAPPING.get_datasets(project, service.reader))
        assert [(dataset.key, dataset.label) for dataset in datasets] == [
            ('1', 'Legacy collection'), ('10', 'Other collection'),
        ]
        result = service.mapping(service.reader(datasets[0]))
        data = asdict(result.metadata)
        for field, value in expected.items():
            assert data[field] == value, field
        assert result.metadata.identifier is None
        assert result.metadata.additional_titles == []
        assert result.metadata.processing == []
        assert result.metadata.software == []
        assert [person.name for person in result.metadata.publishers] == ['Legacy repository']
        assert [person.name for person in result.metadata.rights_holders] == ['Legacy holder', 'Legacy holder']
        creator, = result.metadata.creators
        assert (creator.name, creator.given_name, creator.family_name) == ('Legacy creator', 'Given', 'Family')
        assert creator.identifiers == [Identifier('creator-id', 'ISNI')]
        assert creator.affiliations == [Affiliation('First institution')]
        contributor, = result.metadata.contributors
        assert contributor.name == 'Legacy contributor'
        assert contributor.contributor_type == 'ContactPerson'
        assert contributor.name_type == 'Personal'
        payload = service.compute_payload(datasets[0], 'owner@example.test')
        assert payload.payload['technicalMetadata']['schema'] == {'key': 'RDDM', 'version': '9.3'}
        assert payload.payload['technicalMetadata']['archiveDate'] == 1000
        assert payload.payload['descriptiveMetadata']['language'] == 'DEU'
        assert payload.payload['descriptiveMetadata']['dataSources']['dataSource'][0]['dataSourceDetail'] == 'TRIAL'
        assert not result.issues
        assert payload.provenance
        for row in payload.provenance:
            if not row.unsuccessful:
                assert pointer_value(payload.payload, row.output_path) == row.output_value
        assert not any(row.outcome == 'untraced' for row in payload.provenance)
        assert any(row.outcome == 'skipped' and row.reason == 'Legacy first-answer selection'
                   for row in payload.provenance)
        other = service.mapping(service.reader(datasets[1])).metadata
        assert other.title == 'Other title'
        assert [person.name for person in other.creators] == ['Other creator']
        assert other.keywords == [' keyword ', ' keyword ']
        assert other.funding_references == result.metadata.funding_references


def test_legacy_xml_and_rest_share_canonical_metadata(legacy_project, django_assert_num_queries):
    project, _ = legacy_project
    with django_assert_num_queries(1):
        xml = build_xml_export_service(project, profile=LEGACY_MAPPING, collect_mapping=True)
    with django_assert_num_queries(0):
        datasets = LEGACY_MAPPING.get_datasets(project, xml.reader)
        first, second = xml.compute_files(datasets)
    root = ElementTree.fromstring(first.xml_data)
    ns = '{http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements}'
    assert root.findtext(f'{ns}title') == 'Legacy title'
    assert root.findtext(f'{ns}language') == 'deu'
    assert root.find(f'{ns}dataSources/{ns}dataSource').get('dataSourceDetail') == 'Trial'
    assert root.findtext(f'{ns}creators/{ns}creator/{ns}creatorName') == 'Legacy creator'
    assert root.find(f'{ns}creators/{ns}creator/{ns}nameIdentifier').get('nameIdentifierScheme') == 'ISNI'
    assert root.findtext(f'{ns}creators/{ns}creator/{ns}creatorAffiliation') == 'First institution'
    assert root.find(f'{ns}identifier') is None
    assert 'identifier' in first.missing_fields
    assert b'Other creator' in second.xml_data
    assert any(row.outcome == 'skipped' and row.field.endswith('.name_type') for row in first.provenance)


@pytest.mark.parametrize('title, marker, expected', [
    ('', 'Collection', 'Collection'), ('', '', 'Dataset #4'), (' Title ', 'Collection', ' Title '),
])
def test_legacy_blank_first_answer_and_title_fallbacks(db, title, marker, expected):
    project = Project.objects.create(title='Project title is not a fallback')
    add_answer(project, 'project/dataset/id', marker, set_index=3)
    add_answer(project, 'project/dataset/title', title, set_index=3)
    add_answer(project, 'project/dataset/title', 'Ignored later title', set_index=3, collection_index=1)
    read = LEGACY_MAPPING.build_reader(project)
    dataset, = LEGACY_MAPPING.get_datasets(project, read)
    assert LEGACY_MAPPING.compute_metadata(read(dataset)).metadata.title == expected


def test_legacy_does_not_discover_titles_or_nested_markers_and_rejects_duplicate_indices(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Title without marker')
    add_answer(project, 'project/dataset/id', 'Nested marker', set_prefix='9')
    read = LEGACY_MAPPING.build_reader(project)
    assert LEGACY_MAPPING.get_datasets(project, read) == []
    add_answer(project, 'project/dataset/id', 'First marker')
    add_answer(project, 'project/dataset/id', 'Duplicate marker', collection_index=1)
    with pytest.raises(ValueError, match='unique set indices'):
        LEGACY_MAPPING.get_datasets(project, LEGACY_MAPPING.build_reader(project))


def test_legacy_subject_fallback_depends_on_answer_presence_not_truth(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/id', 'Dataset', set_index=1)
    add_answer(project, 'project/research_field/title', 'Project subject')
    read = LEGACY_MAPPING.build_reader(project)
    dataset, = LEGACY_MAPPING.get_datasets(project, read)
    assert LEGACY_MAPPING.compute_metadata(read(dataset)).metadata.subject_areas[0].additional_name == 'Project subject'
    add_answer(project, 'project/dataset/subject', '', set_index=1)
    read = LEGACY_MAPPING.build_reader(project)
    assert LEGACY_MAPPING.compute_metadata(read(dataset)).metadata.subject_areas == []


def test_legacy_namespace_collisions_do_not_enable_arbitrary_first_answers(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/id', 'Collection')
    title = add_answer(project, 'project/dataset/title', 'First title')
    other = add_namespaced_attribute('project/dataset/title', 'https://other.test')
    project.values.create(attribute=other, text='Other title')
    read = LEGACY_MAPPING.build_reader(project)
    dataset, = LEGACY_MAPPING.get_datasets(project, read)
    result = LEGACY_MAPPING.compute_metadata(read(dataset))
    assert result.metadata.title == 'Collection'
    assert any(issue.reason == 'Ambiguous Attribute' for issue in result.issues)
    context = read(dataset)
    assert first_text(context, source=Source(title.attribute.uri), target='title') == 'First title'
    language = add_attribute('project/dataset/language')
    options = [Option.objects.create(uri_prefix=namespace, uri_path='language/de')
               for namespace in ('https://first.test', 'https://second.test')]
    for index, option in enumerate(options):
        project.values.create(attribute=language, option=option, collection_index=index)
    context = LEGACY_MAPPING.build_reader(project)(dataset)
    assert first_option(
        context, source=Source(language.pk), target='language', option_map={'language/de': 'deu'},
    ) is None
    assert any(issue.reason == 'Ambiguous Option path' for issue in context.issues)
    assert first_option(context, source=Source(language), target='language',
                        option_map={options[0].uri: 'deu'}) == 'deu'


def test_legacy_snapshots_reuse_only_saved_answers(legacy_project, django_assert_num_queries):
    project, _ = legacy_project
    snapshot = Snapshot.objects.create(project=project, title='Saved answers')
    project.values.filter(snapshot=None, attribute__path='project/dataset/title').update(text='Current title')
    with django_assert_num_queries(1):
        service = build_export_service(project, snapshot=snapshot, profile=LEGACY_MAPPING, collect_mapping=True)
    with django_assert_num_queries(0):
        dataset = LEGACY_MAPPING.get_datasets(project, service.reader)[0]
        payload = service.compute_payload(dataset, 'owner@example.test')
    assert payload.payload['descriptiveMetadata']['title'] == 'Legacy title'
    values = [source.value for row in payload.provenance for source in row.sources
              if hasattr(source.value, 'snapshot_id')]
    assert values
    assert all(value.snapshot_id == snapshot.pk for value in values)


def test_legacy_storage_captures_scope_and_ignores_missing_destinations(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/id', 'First', set_index=1)
    add_answer(project, 'project/dataset/id', 'Other', set_index=10)
    add_attribute('project/dataset/radar_url')
    saved = add_answer(project, 'project/dataset/radar_id', 'Saved', set_index=1)
    nested = add_answer(project, 'project/dataset/radar_id', 'Nested', set_prefix='1', set_index=1)
    snapshot = Snapshot.objects.create(project=project, title='Before export')
    service = build_export_service(project, profile=LEGACY_MAPPING)
    dataset = LEGACY_MAPPING.get_datasets(project, service.reader)[0]
    LEGACY_MAPPING.store_result(project, dataset, 'confirmed', 'https://radar.test/dataset/confirmed')
    saved.refresh_from_db()
    nested.refresh_from_db()
    assert saved.text == 'confirmed'
    assert nested.text == 'Nested'
    assert project.values.get(snapshot=snapshot, attribute=saved.attribute, set_prefix='').text == 'Saved'
    assert not project.values.filter(snapshot=None, attribute=saved.attribute, set_index=10).exists()
    broken = replace(dataset, scope={**dataset.scope, 'destinations': {'radar_id': None}})
    with pytest.raises(ExportStoreError):
        LEGACY_MAPPING.store_result(project, broken, 'invalid', 'https://radar.test/invalid')
    # A mapping can have no configured local destinations at all.
    disabled = replace(dataset, scope={**dataset.scope, 'destinations': {}})
    LEGACY_MAPPING.store_result(project, disabled, 'remote-only', 'https://radar.test/remote-only')


def test_legacy_named_adapters_use_native_registration_and_have_no_importer(settings, db):
    settings.PROJECT_EXPORTS = [(name, name, f'rdmo_radar.exports.{name}') for name in (
        'RadarLegacyExport', 'RadarLegacyExportProvider', 'RadarLegacyCredentialsExportProvider',
    )]
    plugins = get_plugins('PROJECT_EXPORTS')
    assert all(plugin.mapping is LEGACY_MAPPING for plugin in plugins.values())
    assert LEGACY_FIELDS.writers == {}
    with pytest.raises(UnsupportedImportMapping):
        build_import_service(None, profile=LEGACY_MAPPING)


def test_legacy_storage_skips_uninstalled_destination_attributes(db):
    project = Project.objects.create(title='Project')
    marker = add_answer(project, 'project/dataset/id', 'Dataset')
    read = LEGACY_MAPPING.build_reader(project)
    dataset, = LEGACY_MAPPING.get_datasets(project, read)
    LEGACY_MAPPING.store_result(project, dataset, 'confirmed', 'https://radar.test/confirmed')
    assert list(project.values.values_list('pk', flat=True)) == [marker.pk]


def test_legacy_option_defaults_do_not_infer_language_from_text(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/id', 'Dataset')
    add_answer(project, 'project/dataset/creator/name', 'Creator', set_prefix='0')
    add_answer(project, 'project/dataset/creator/name_identifier', 'raw-id', set_prefix='0')
    add_answer(project, 'project/dataset/contributor/name', 'Contributor', set_prefix='0')
    add_answer(project, 'project/dataset/language', 'Deutsch')
    read = LEGACY_MAPPING.build_reader(project)
    dataset, = LEGACY_MAPPING.get_datasets(project, read)
    metadata = LEGACY_MAPPING.compute_metadata(read(dataset)).metadata
    assert metadata.language is None
    assert metadata.creators[0].identifiers == [Identifier('raw-id', 'ORCID')]
    assert metadata.creators[0].name_type == 'Personal'
    assert metadata.contributors[0].contributor_type == 'Other'


def test_legacy_diagnostics_do_not_leak_between_datasets(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/id', 'First', set_index=1)
    add_answer(project, 'project/dataset/id', 'Other', set_index=10)
    unknown = Option.objects.create(uri_prefix='https://example.org', uri_path='language/unknown')
    add_answer(project, 'project/dataset/language', '', option=unknown, set_index=1)
    service = build_export_service(project, profile=LEGACY_MAPPING)
    first, other = LEGACY_MAPPING.get_datasets(project, service.reader)
    assert service.compute_payload(first, 'owner@example.test').issues
    assert not service.compute_payload(other, 'owner@example.test').issues
