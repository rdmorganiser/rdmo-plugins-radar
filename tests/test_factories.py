"""Default assembly and independently replaceable service dependencies."""
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from rdmo.core.exports import prettify_xml
from rdmo.projects.models import Project, Snapshot

from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.factories import build_export_service, build_import_service, build_xml_export_service
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.importer import write_metadata
from rdmo_radar.metadata.template_framework import compute_next_dataset_index
from rdmo_radar.metadata.types import Agent, MappingIssue, MappingResult, RadarMetadata
from rdmo_radar.metadata.xml import to_xml_payload

from .helpers import add_answer, add_attribute, complete_metadata, make_import


@pytest.mark.parametrize('factory', [build_export_service, build_xml_export_service])
def test_default_reader_prepares_once_and_isolates_contexts(db, django_assert_num_queries, factory):
    project = Project.objects.create(title='Project')
    for index in range(50):
        add_answer(project, 'project/dataset/title', f'Dataset {index}', set_index=index)
    kwargs = {'writer': Mock()} if factory is build_export_service else {}
    with django_assert_num_queries(1):
        service = factory(project, **kwargs)
    with django_assert_num_queries(0):
        for index in range(50):
            context = service.reader(index)
            assert service.mapping(context).metadata.title == f'Dataset {index}'
        first = service.reader(0)
        second = service.reader(1)
        assert first.values is second.values
        assert first.placements is second.placements
        first.issues.append(MappingIssue('title', 'First only'))
        result = service.mapping(second)
        assert MappingIssue('title', 'First only') not in result.issues


def test_prepared_reader_honors_snapshot_and_rebuild(db):
    project = Project.objects.create(title='Project')
    other = Project.objects.create(title='Other')
    snapshot = Snapshot.objects.create(project=project, title='Snapshot')
    live = add_answer(project, 'project/dataset/title', 'Live')
    add_answer(project, 'project/dataset/title', 'Saved', snapshot=snapshot)
    add_answer(other, 'project/dataset/title', 'Other')
    service = build_xml_export_service(project)
    saved = build_xml_export_service(project, snapshot=snapshot)
    separate = build_xml_export_service(other)
    live.text = 'Changed'
    live.save()
    assert service.mapping(service.reader(0)).metadata.title == 'Live'
    assert saved.mapping(saved.reader(0)).metadata.title == 'Saved'
    assert separate.mapping(separate.reader(0)).metadata.title == 'Other'
    rebuilt = build_xml_export_service(project)
    assert rebuilt.mapping(rebuilt.reader(0)).metadata.title == 'Changed'


def test_rest_defaults_prepare_and_store_supplied_url_without_provider_settings(db, settings):
    del settings.RADAR_PROVIDER
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Draft', set_index=2)
    add_attribute('project/dataset/radar_id')
    add_attribute('project/dataset/radar_url')
    service = build_export_service(project, clock=lambda: 12.345)
    payload = service.compute_payload(2, 'owner@test')
    assert payload.payload['technicalMetadata']['archiveDate'] == 12345
    assert payload.payload['descriptiveMetadata']['title'] == 'Draft'
    assert not project.values.filter(attribute__path='project/dataset/radar_id').exists()
    url = 'https://radar-staging.example.test/radar/de/dataset/confirmed'
    result = service.store_result(2, 'confirmed', url)
    assert result.radar_url == url
    assert project.values.get(attribute__path='project/dataset/radar_id').text == 'confirmed'
    assert project.values.get(attribute__path='project/dataset/radar_url').text == url


def test_custom_mapping_partial_for_rest_preserves_other_fields(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    mapping = partial(compute_metadata, creators=lambda context: [Agent('Custom')])
    service = build_export_service(project, mapping=mapping)
    result = service.compute_payload(0, 'owner@test')
    assert result.payload['descriptiveMetadata']['title'] == 'Dataset'
    assert result.payload['descriptiveMetadata']['creators']['creator'][0]['creatorName'] == 'Custom'
    assert service.mapping is mapping


def test_custom_mapping_partial_and_xml_defaults_without_radar_settings(db, settings):
    del settings.RADAR_PROVIDER
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    mapping = partial(compute_metadata, creators=lambda context: [Agent('Custom')])
    service = build_xml_export_service(project, mapping=mapping)
    result = service.mapping(service.reader(0))
    assert result.metadata.title == 'Dataset'
    assert result.metadata.creators == [Agent('Custom')]
    xml_file = service.compute_files([0])[0]
    assert b'Custom' in xml_file.xml_data
    assert not xml_file.validation_failed
    assert service.mapping is mapping


def test_xml_default_output_matches_existing_renderer():
    metadata = complete_metadata()
    service = build_xml_export_service(
        None, reader=lambda index: None, mapping=lambda context: MappingResult(metadata),
    )
    xml_file = service.compute_files([0])[0]
    assert xml_file.xml_data == prettify_xml(RadarExportRenderer().render(to_xml_payload(metadata)))
    assert not xml_file.has_warnings


def test_import_prepares_current_values_once_and_stages_without_saving(db, django_assert_num_queries, settings):
    del settings.RADAR_PROVIDER
    plugin = make_import()
    plugin.current_project = Project.objects.create(title='Project')
    add_answer(plugin.current_project, 'project/dataset/title', 'Existing', set_index=4)
    snapshot = Snapshot.objects.create(project=plugin.current_project, title='Snapshot')
    add_answer(plugin.current_project, 'project/dataset/title', 'Saved', set_index=20, snapshot=snapshot)
    add_answer(plugin.current_project, 'project/dataset/id', 'Marker', set_index=30)
    persisted = list(plugin.current_project.values.values())
    with django_assert_num_queries(1):
        service = build_import_service(plugin)
    with django_assert_num_queries(0):
        issues = service.process(ElementTree.fromstring(
            '<radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">'
            '<title>Imported</title></radarDataset>'
        ))
    title = next(value for value in plugin.values if value.attribute.path == 'project/dataset/title')
    assert title.text == 'Imported'
    assert title.set_index == 5
    assert title.pk is None
    assert isinstance(issues, tuple)
    assert list(plugin.current_project.values.values()) == persisted


def test_import_accepts_independent_funding_mapping():
    plugin = make_import()

    def funding(context, references):
        context.add('project/funder/name', 'Custom funding', dataset=False)

    mapping = partial(write_metadata, funding=funding)
    service = build_import_service(
        plugin, existing_values={}, parser=lambda root: root, mapping=mapping,
    )
    service.process(RadarMetadata(title='Dataset', creators=[Agent('Creator')]))
    assert {(value.attribute.path, value.text) for value in plugin.values} == {
        ('project/dataset/title', 'Dataset'), ('project/dataset/creator/name', 'Creator'),
        ('project/funder/name', 'Custom funding'),
    }


@pytest.mark.parametrize('index', [None, 8])
def test_import_honors_empty_prepared_values_and_explicit_index(index):
    plugin = make_import()
    prepared = {}
    mapping = Mock(return_value=())
    service = build_import_service(
        plugin, set_index=index, existing_values=prepared, parser=lambda root: root, mapping=mapping,
    )
    metadata = RadarMetadata(title='Input')
    assert service.process(metadata) == ()
    mapping.assert_called_once_with(plugin, metadata, set_index=0 if index is None else index, existing_values=prepared)
    assert mapping.call_args.kwargs['existing_values'] is prepared


def test_import_default_preparation_requires_existing_project():
    with pytest.raises(ValueError, match='existing project'):
        build_import_service(make_import())


def test_shared_index_allocation_preserves_title_only_rule():
    values = {
        'project/dataset/title': [SimpleNamespace(set_index=2)],
        'project/dataset/id': [SimpleNamespace(set_index=99)],
    }
    assert compute_next_dataset_index(values) == 3
    assert compute_next_dataset_index({}) == 0


class FalseyCallable:
    def __bool__(self):
        return False

    def __call__(self, *args, **kwargs):
        return ()


@pytest.mark.parametrize('factory, names', [
    (build_export_service, ('reader', 'mapping', 'serializer', 'writer', 'clock')),
    (build_xml_export_service, ('reader', 'mapping', 'serializer', 'renderer', 'validator')),
    (build_import_service, ('parser', 'writer')),
])
def test_explicit_overrides_preserve_falsey_objects_and_skip_unused_defaults(settings, factory, names):
    del settings.RADAR_PROVIDER
    overrides = {name: FalseyCallable() for name in names}
    service = factory(None, **overrides)
    for name, dependency in overrides.items():
        assert getattr(service, name) is dependency
