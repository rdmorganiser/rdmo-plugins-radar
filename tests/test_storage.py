"""Confirmed export persistence, including transaction boundaries and dataset isolation."""
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from django.db import connection

from rdmo.projects.models import Project, Snapshot, Value

from rdmo_radar.client import dataset_page_url
from rdmo_radar.exceptions import ExportStoreError
from rdmo_radar.exports.storage import store_export_result
from rdmo_radar.metadata.api import compute_radar_payload
from rdmo_radar.metadata.types import MappingResult, RadarMetadata
from rdmo_radar.services import RadarExportService

from .helpers import add_answer, add_attribute


@pytest.mark.parametrize('url', [
    'https://radar.example.test/radar/en/dataset/radar-1',
    'https://radar-staging.example.test/radar/de/dataset/radar-1',
    'https://radar-staging.example.test/custom/path?source=confirmed#details',
])
def test_storage_updates_only_selected_live_flat_values(db, url):
    project = Project.objects.create(title='Selected project')
    other = Project.objects.create(title='Other project')
    snapshot = Snapshot.objects.create(project=project, title='Snapshot')
    selected = []
    untouched = []
    for path in ('project/dataset/radar_id', 'project/dataset/radar_url'):
        selected.append(add_answer(project, path, 'Previous', set_index=1))
        untouched.extend([
            add_answer(project, path, 'Other dataset', set_index=0),
            add_answer(project, path, 'Dataset ten', set_index=10),
            add_answer(project, path, 'Snapshot', set_index=1, snapshot=snapshot),
            add_answer(project, path, 'Nested', set_index=1, set_prefix='1'),
            add_answer(project, path, 'Other collection', set_index=1, collection_index=1),
            add_answer(other, path, 'Other project', set_index=1),
        ])
    untouched_ids = [value.pk for value in untouched]
    before = list(Value.objects.filter(pk__in=untouched_ids).values())

    assert store_export_result(project, '1', 'radar-1', url) is None
    for value, text in zip(selected, ('radar-1', url), strict=True):
        value.refresh_from_db()
        assert value.text == text
    assert list(Value.objects.filter(pk__in=untouched_ids).values()) == before
    assert Value.objects.count() == len(selected) + len(untouched)


@pytest.mark.parametrize('installed', [(), ('radar_id',), ('radar_url',), ('radar_id', 'radar_url')])
def test_storage_skips_missing_attributes_and_creates_available_values(db, installed):
    project = Project.objects.create(title='Project')
    for key in installed:
        add_attribute(f'project/dataset/{key}')
    url = 'https://radar-staging.example.test/radar/en/dataset/radar-1'
    assert store_export_result(project, 3, 'radar-1', url) is None
    values = list(project.values.all())
    assert {value.attribute.path for value in values} == {f'project/dataset/{key}' for key in installed}
    assert {value.text for value in values} == {
        'radar-1' if key == 'radar_id' else url for key in installed
    }
    assert all((value.set_index, value.set_prefix, value.collection_index, value.snapshot_id) == (3, '', 0, None)
               for value in values)


@pytest.mark.parametrize('existing', [False, True])
def test_storage_rolls_back_id_if_url_save_fails(db, monkeypatch, existing):
    project = Project.objects.create(title='Project')
    for path in ('project/dataset/radar_id', 'project/dataset/radar_url'):
        add_attribute(path)
        if existing:
            add_answer(project, path, 'Previous', set_index=3)
    before = list(project.values.values())
    original_save = Value.save

    def save(value, *args, **kwargs):
        if value.attribute.path == 'project/dataset/radar_url':
            raise RuntimeError('Local write failed')
        return original_save(value, *args, **kwargs)

    monkeypatch.setattr(Value, 'save', save)
    url = 'https://radar.example.test/radar/en/dataset/radar-1'
    with pytest.raises(ExportStoreError) as caught:
        store_export_result(project, '3', 'radar-1', url)
    assert (caught.value.set_index, caught.value.radar_id, caught.value.radar_url) == (3, 'radar-1', url)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert str(caught.value.__cause__) == 'Local write failed'
    assert 'Local write failed' not in str(caught.value)
    assert list(project.values.values()) == before


def test_direct_storage_needs_no_service_or_project_data_preparation(db, monkeypatch):
    project = Project.objects.create(title='Project')
    add_attribute('project/dataset/radar_id')
    add_attribute('project/dataset/radar_url')
    preparation = Mock(side_effect=AssertionError('Storage must not prepare mapping data'))
    monkeypatch.setattr(RadarExportService, '__init__', preparation)
    for module in ('rdmo_radar.metadata.values', 'rdmo_radar.mappings.template_framework'):
        monkeypatch.setattr(f'{module}.fetch_project_values', preparation)
        monkeypatch.setattr(f'{module}.fetch_catalog_placements', preparation)

    url = 'https://radar-staging.example.test/radar/de/dataset/confirmed'
    assert store_export_result(project, '3', 'confirmed', url) is None

    preparation.assert_not_called()
    assert project.values.get(attribute__path='project/dataset/radar_id').text == 'confirmed'
    assert project.values.get(attribute__path='project/dataset/radar_url').text == url


@pytest.mark.django_db(transaction=True)
def test_remote_creation_precedes_local_transaction_and_failure_retains_confirmed_id(monkeypatch):
    project = Project.objects.create(title='Project')
    add_attribute('project/dataset/radar_id')
    add_attribute('project/dataset/radar_url')
    original_save = Value.save
    calls = []

    def create_dataset(token, workspace, payload):
        assert not connection.in_atomic_block
        calls.append('remote')
        return {'id': 'confirmed-id'}

    def save(value, *args, **kwargs):
        assert connection.in_atomic_block
        calls.append(value.attribute.path)
        if value.attribute.path == 'project/dataset/radar_url':
            raise RuntimeError('Local write failed')
        return original_save(value, *args, **kwargs)

    client = SimpleNamespace(
        radar_url='https://radar-staging.example.test/', create_dataset=Mock(side_effect=create_dataset),
    )
    service = RadarExportService(
        lambda index: None, lambda context: MappingResult(RadarMetadata(title='Draft')), compute_radar_payload,
        partial(store_export_result, project),
    )
    monkeypatch.setattr(Value, 'save', save)
    payload = service.compute_payload(3, 'owner@example.test')
    dataset = client.create_dataset('token', 'workspace', payload.payload)
    url = dataset_page_url(client.radar_url, dataset['id'])
    with pytest.raises(ExportStoreError) as caught:
        service.store_result(3, dataset['id'], url)

    assert caught.value.radar_id == 'confirmed-id'
    assert caught.value.radar_url == url
    assert calls == ['remote', 'project/dataset/radar_id', 'project/dataset/radar_url']
    client.create_dataset.assert_called_once()
    assert not project.values.exists()
