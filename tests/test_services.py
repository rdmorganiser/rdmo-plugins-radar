"""Service operations with fakes; adapters and request/session state stay outside."""
import os
import subprocess
import sys
from copy import deepcopy
from functools import partial
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from rdmo.core.exports import prettify_xml

from rdmo_radar.exceptions import ExportStoreError, XmlExportError
from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import get_radar_validation_errors
from rdmo_radar.metadata.api import compute_radar_payload
from rdmo_radar.metadata.importer import write_metadata
from rdmo_radar.metadata.types import MappingIssue, MappingResult, RadarMetadata
from rdmo_radar.metadata.xml import parse_xml, to_xml_payload
from rdmo_radar.services import (
    ExportPayload,
    ExportResult,
    RadarExportService,
    RadarImportService,
    RadarXmlExportService,
)

from .helpers import complete_metadata, make_import, make_read_context


def make_export_service(metadata=None, issues=()):
    context = object()
    service = RadarExportService(
        reader=Mock(return_value=context),
        mapping=Mock(return_value=MappingResult(metadata if metadata is not None else RadarMetadata(), issues)),
        serializer=Mock(wraps=compute_radar_payload),
        writer=Mock(return_value=None),
        clock=Mock(return_value=1_725_000_000.123),
    )
    calls = Mock()
    for name, dependency in (
        ('reader', service.reader), ('mapping', service.mapping), ('clock', service.clock),
        ('serializer', service.serializer), ('writer', service.writer),
    ):
        calls.attach_mock(dependency, name)
    return service, context, calls


@pytest.mark.parametrize('title', [None, '', 'Existing title'])
def test_payload_maps_once_without_mutating_metadata_or_storing(title):
    metadata = RadarMetadata(title=title)
    original = deepcopy(metadata)
    issues = (MappingIssue('resource', 'Incomplete draft'),)
    service, context, calls = make_export_service(metadata, issues)

    result = service.compute_payload('10', 'owner@example.test')

    assert result == ExportPayload({
        'technicalMetadata': {
            'retentionPeriod': 10, 'archiveDate': 1_725_000_000_123, 'publishDate': 1_725_000_000_123,
            'responsibleEmail': 'owner@example.test', 'schema': {'key': 'RDDM', 'version': '9.3'},
        },
        'descriptiveMetadata': {'title': title or 'Dataset #11'},
    }, issues)
    assert [call[0] for call in calls.mock_calls] == ['reader', 'mapping', 'clock', 'serializer']
    service.reader.assert_called_once_with(10)
    service.mapping.assert_called_once_with(context)
    service.writer.assert_not_called()
    assert metadata == original


@pytest.mark.parametrize('stage', ['reader', 'mapping', 'serializer', 'clock'])
def test_preparation_failure_never_calls_writer(stage):
    service, _, _ = make_export_service()
    error = ValueError('Preparation failed')
    getattr(service, stage).side_effect = error
    with pytest.raises(ValueError) as caught:
        service.compute_payload(0, 'owner@example.test')
    assert caught.value is error
    service.writer.assert_not_called()


def test_storage_is_independent_of_payload_preparation_and_preserves_confirmed_url():
    service, _, calls = make_export_service()
    url = 'https://radar-staging.example.test/radar/de/dataset/radar-1?source=confirmed#details'

    result = service.store_result('10', 'radar-1', url)

    assert result == ExportResult('radar-1', url)
    assert [call[0] for call in calls.mock_calls] == ['writer']
    service.writer.assert_called_once_with(10, 'radar-1', url)


def test_local_failure_retains_confirmed_id_and_url_without_retry():
    service, _, _ = make_export_service()
    error = ValueError('Private database detail')
    service.writer.side_effect = error
    url = 'https://radar-staging.example.test/radar/en/dataset/radar-1'
    with pytest.raises(ExportStoreError) as caught:
        service.store_result(10, 'radar-1', url)
    assert (caught.value.set_index, caught.value.radar_id, caught.value.radar_url) == (10, 'radar-1', url)
    assert caught.value.__cause__ is error
    assert 'Private database detail' not in str(caught.value)
    service.writer.assert_called_once_with(10, 'radar-1', url)
    service.reader.assert_not_called()


def test_storage_error_propagates_unchanged_without_double_wrapping():
    service, _, _ = make_export_service()
    url = 'https://radar-staging.example.test/radar/en/dataset/confirmed'
    error = ExportStoreError(3, 'confirmed', url)
    cause = RuntimeError('Private database detail')
    error.__cause__ = cause
    service.writer.side_effect = error

    with pytest.raises(ExportStoreError) as caught:
        service.store_result(3, 'confirmed', url)

    assert caught.value is error
    assert caught.value.__cause__ is cause
    service.writer.assert_called_once_with(3, 'confirmed', url)
    service.reader.assert_not_called()


def make_xml_service(metadata=None, issues=()):
    return RadarXmlExportService(
        reader=Mock(return_value=object()),
        mapping=Mock(return_value=MappingResult(metadata if metadata is not None else complete_metadata(), issues)),
        serializer=Mock(return_value={'xml': 'payload'}),
        renderer=Mock(return_value=b'<radarDataset/>'),
        validator=Mock(return_value=()),
    )


def test_xml_maps_once_and_matches_existing_renderer_and_schema():
    context = make_read_context()
    issues = (MappingIssue('title', 'Example warning'),)
    metadata = complete_metadata()
    service = RadarXmlExportService(
        reader=Mock(return_value=context), mapping=Mock(return_value=MappingResult(metadata, issues)),
        serializer=to_xml_payload,
        renderer=lambda payload: prettify_xml(RadarExportRenderer().render(payload)),
        validator=get_radar_validation_errors,
    )
    file = service.compute_files([0])[0]
    service.reader.assert_called_once_with(0)
    service.mapping.assert_called_once_with(context)
    assert file.xml_data == prettify_xml(RadarExportRenderer().render(to_xml_payload(metadata)))
    assert file.missing_fields == file.validation_errors == ()
    assert file.issues is issues
    assert file.has_warnings and not file.validation_failed


def test_xml_preserves_order_and_safe_unique_file_names():
    titles = ['../folder/name', 'Same', 'same', 'Same', None, ' . ', 'x' * 200, 'bad\x00\x1f\x7f\\name']
    service = make_xml_service()
    service.reader.side_effect = lambda index: index
    service.mapping.side_effect = lambda index: MappingResult(complete_metadata(title=titles[index]))
    files = service.compute_files(range(len(titles)))
    assert [file.file_name for file in files] == [
        '_folder_name.xml', 'Same.xml', 'same-2.xml', 'Same-3.xml', '5.xml', '6.xml',
        f'{"x" * 180}.xml', 'bad____name.xml',
    ]
    assert [call.args[0] for call in service.mapping.call_args_list] == list(range(len(titles)))
    assert service.renderer.call_count == service.validator.call_count == len(titles)
    assert service.compute_files([]) == []


def test_xml_keeps_draft_completeness_schema_and_mapping_warnings_separate():
    issues = (MappingIssue('title', 'Mapping warning'),)
    service = make_xml_service(RadarMetadata(title='Draft'), issues)
    service.validator.return_value = ('Schema violation',)
    file = service.compute_files([0])[0]
    assert 'identifier' in file.missing_fields
    assert file.validation_errors == ('Schema violation',)
    assert file.issues is issues
    assert file.has_warnings and not file.validation_failed


def test_xml_validator_failure_returns_a_warning_flag_without_discarding_xml():
    service = make_xml_service()
    service.validator.side_effect = RuntimeError('Private validation detail')
    file = service.compute_files([0])[0]
    assert file.xml_data == b'<radarDataset/>'
    assert file.validation_errors == file.missing_fields == ()
    assert file.validation_failed and file.has_warnings
    service.validator.assert_called_once_with(file.xml_data)


@pytest.mark.parametrize(('stage', 'file_name'), [
    ('reader', '1.xml'), ('mapping', '1.xml'), ('serializer', 'Dataset.xml'), ('renderer', 'Dataset.xml'),
])
def test_xml_generation_failure_identifies_file_without_exposing_internal_message(stage, file_name):
    service = make_xml_service()
    error = RuntimeError('Private rendering detail')
    getattr(service, stage).side_effect = error
    with pytest.raises(XmlExportError) as caught:
        service.compute_files([0])
    assert caught.value.file_name == file_name
    assert 'Private rendering detail' not in str(caught.value)
    assert caught.value.__cause__ is error
    service.validator.assert_not_called()


def test_import_service_uses_configured_writer_to_stage_unsaved_values():
    plugin = make_import()
    root = ElementTree.fromstring('''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <title>Imported dataset</title><version>Unmapped version</version>
        </radarDataset>
    ''')
    service = RadarImportService(parse_xml, partial(write_metadata, plugin, set_index=10, existing_values={}))
    issues = service.process(root)
    assert isinstance(issues, tuple)
    assert issues[0].field == 'version'
    assert [(value.text, value.set_index, value.pk) for value in plugin.values] == [('Imported dataset', 10, None)]


def test_import_service_passes_parser_result_directly_to_writer_and_returns_only_issues():
    root = object()
    metadata = RadarMetadata(title='Parsed')
    issues = (MappingIssue('title', 'Warning'),)
    parser = Mock(return_value=metadata)
    writer = Mock(return_value=issues)
    service = RadarImportService(parser, writer)
    assert service.process(root) is issues
    parser.assert_called_once_with(root)
    writer.assert_called_once_with(metadata)


def test_import_parser_failure_does_not_stage_values():
    error = ValueError('Invalid XML')
    writer = Mock()
    service = RadarImportService(Mock(side_effect=error), writer)
    with pytest.raises(ValueError) as caught:
        service.process(object())
    assert caught.value is error
    writer.assert_not_called()


def test_services_and_payload_builder_run_without_django_settings_or_adapter_imports():
    environment = dict(os.environ)
    environment.pop('DJANGO_SETTINGS_MODULE', None)
    result = subprocess.run([sys.executable, '-c', '''
import sys
from rdmo_radar.client import RadarClient
from rdmo_radar.services import RadarExportService, RadarXmlExportService, RadarImportService
from rdmo_radar.metadata.api import compute_radar_payload
from rdmo_radar.metadata.types import MappingResult, RadarMetadata
metadata = RadarMetadata(title='Draft')
assert RadarClient('https://radar.test', 'id', 'secret', 'https://rdmo.test').timeout == 30
service = RadarExportService(
    lambda index: None, lambda context: MappingResult(metadata), compute_radar_payload,
    lambda *args: None, clock=lambda: 1,
)
assert service.compute_payload(0, 'owner').payload['descriptiveMetadata']['title'] == 'Draft'
assert service.store_result(0, 'id', 'url').radar_url == 'url'
xml = RadarXmlExportService(lambda index: None, lambda context: MappingResult(metadata),
                            lambda value: {}, lambda value: b'<xml/>', lambda value: ())
assert xml.compute_files([0])[0].xml_data == b'<xml/>'
assert RadarImportService(lambda root: metadata, lambda value: ()).process(None) == ()
assert not any(name.startswith(('django', 'rest_framework', 'rdmo.', 'rdmo_radar.exports')) for name in sys.modules)
'''], env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
