"""RADAR operations with explicit dependencies and no presentation or plugin lifecycle."""
import logging
import re
import time
from dataclasses import dataclass, replace

from .exceptions import ExportStoreError, XmlExportError
from .mappings import ExportDataset
from .metadata.provenance import project_provenance
from .metadata.types import MappingAttempt, MappingIssue, MappingSource
from .metadata.validation import missing_required_fields

logger = logging.getLogger(__name__)


def _project_provenance(provenance, metadata, events, output, *, xml=False):
    try:
        return project_provenance(provenance, metadata, events, output, xml=xml)
    except Exception as error:
        logger.warning('Could not prepare RADAR provenance: error_type=%s', type(error).__name__)
        return None


@dataclass(frozen=True)
class ExportPayload:
    payload: dict
    issues: tuple[MappingIssue, ...] = ()
    provenance: tuple[MappingAttempt, ...] | None = None


@dataclass(frozen=True)
class ExportResult:
    radar_id: str
    radar_url: str


def store_confirmed_result(writer, selection, radar_id, radar_url):
    """Optional local storage, shared by services and reconstructed OAuth callbacks."""
    try:
        if writer is not None:
            writer(selection, radar_id, radar_url)
    except ExportStoreError:
        raise
    except Exception as error:
        key = selection.key if isinstance(selection, ExportDataset) else selection
        raise ExportStoreError(key, radar_id, radar_url) from error
    return ExportResult(radar_id, radar_url)


@dataclass(frozen=True)
class XmlExportFile:
    file_name: str
    xml_data: bytes
    missing_fields: tuple[str, ...]
    validation_errors: tuple[str, ...]
    issues: tuple[MappingIssue, ...] = ()
    validation_failed: bool = False
    provenance: tuple[MappingAttempt, ...] | None = None

    @property
    def has_warnings(self):
        return bool(self.missing_fields or self.validation_errors or self.issues or self.validation_failed)


class RadarExportService:
    def __init__(self, reader, mapping, serializer, writer, *, clock=time.time, trace_serializer=False):
        self.reader = reader
        self.mapping = mapping
        self.serializer = serializer
        self.writer = writer
        self.clock = clock
        self.trace_serializer = trace_serializer

    def compute_payload(self, set_index, responsible_email, *, mapping_result=None) -> ExportPayload:
        """Prepare the request and diagnostics without performing a remote request or local write."""
        set_index = set_index if isinstance(set_index, ExportDataset) else int(set_index)
        result = mapping_result if mapping_result is not None else self.mapping(self.reader(set_index))
        metadata = result.metadata
        provenance = result.provenance
        if not metadata.title:
            title = set_index.label if isinstance(set_index, ExportDataset) else f'Dataset #{set_index + 1}'
            metadata = replace(metadata, title=title or 'Dataset')
            if provenance is not None:
                provenance += (MappingAttempt('title', (MappingSource('Export dataset label', title or 'Dataset'),),
                                              title or 'Dataset', 'defaulted', 'Draft title fallback'),)
        events = []
        kwargs = {'record_output': lambda *event: events.append(event)} if self.trace_serializer else {}
        payload = self.serializer(
            metadata, responsible_email=responsible_email, timestamp=int(self.clock() * 1000),
            **kwargs,
        )
        provenance = _project_provenance(provenance, metadata, events, payload) if self.trace_serializer else None
        return ExportPayload(payload, result.issues, provenance)

    def store_result(self, set_index, radar_id, radar_url) -> ExportResult:
        """Record an ID and complete URL after the caller has confirmed remote creation."""
        set_index = set_index if isinstance(set_index, ExportDataset) else int(set_index)
        return store_confirmed_result(self.writer, set_index, radar_id, radar_url)


class RadarXmlExportService:
    def __init__(self, reader, mapping, serializer, renderer, validator, *, trace_serializer=False):
        self.reader = reader
        self.mapping = mapping
        self.serializer = serializer
        self.renderer = renderer
        self.validator = validator
        self.trace_serializer = trace_serializer

    def compute_files(self, indices) -> list[XmlExportFile]:
        files = []
        names = set()
        for set_index in indices:
            set_index = set_index if isinstance(set_index, ExportDataset) else int(set_index)
            fallback = ((set_index.fallback_file_stem or set_index.label or set_index.key)
                        if isinstance(set_index, ExportDataset)
                        else str(set_index + 1))
            fallback_stem = re.sub(r'[/\\\x00-\x1f\x7f]', '_', fallback).strip(' .')[:180] or 'dataset'
            file_name = f'{fallback_stem}.xml'
            try:
                result = self.mapping(self.reader(set_index))
                title = result.metadata.title or fallback
                stem = re.sub(r'[/\\\x00-\x1f\x7f]', '_', title).strip(' .')[:180] or fallback_stem
                file_name = f'{stem}.xml'
                suffix = 2
                while file_name.casefold() in names:
                    file_name = f'{stem}-{suffix}.xml'
                    suffix += 1
                names.add(file_name.casefold())
                events = []
                kwargs = {'record_output': lambda *event, events=events: events.append(event)} if (
                    self.trace_serializer
                ) else {}
                xml_data = self.renderer(self.serializer(result.metadata, **kwargs))
            except Exception as error:
                raise XmlExportError(file_name) from error

            missing_fields = missing_required_fields(result.metadata)
            validation_failed = False
            try:
                validation_errors = tuple(self.validator(xml_data))
            except Exception:
                validation_errors = ()
                validation_failed = True
            files.append(XmlExportFile(
                file_name, xml_data, missing_fields, validation_errors, result.issues, validation_failed,
                _project_provenance(result.provenance, result.metadata, events, xml_data, xml=True)
                if self.trace_serializer else None,
            ))
        return files


class RadarImportService:
    def __init__(self, parser, writer):
        self.parser = parser
        self.writer = writer

    def process(self, root) -> tuple[MappingIssue, ...]:
        metadata = self.parser(root)
        return self.writer(metadata)
