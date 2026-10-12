"""Build operation-scoped services with RDMO defaults and explicit overrides."""
from functools import partial

from .metadata.api import compute_radar_payload
from .metadata.builder import compute_metadata
from .metadata.importer import write_metadata
from .metadata.rdmo import RDMOReadContext
from .metadata.values import compute_next_dataset_index, fetch_catalog_placements, fetch_project_values
from .metadata.xml import parse_xml, to_xml_payload
from .services import RadarExportService, RadarImportService, RadarXmlExportService


def _build_reader(project, snapshot=None):
    values = fetch_project_values(project, snapshot)
    placements = fetch_catalog_placements(project.catalog)

    def read(set_index):
        return RDMOReadContext(values, placements, set_index=int(set_index))

    return read


def build_export_service(
    project, *, snapshot=None, reader=None, mapping=None, serializer=None, writer=None, clock=None,
):
    """Prepare one REST export operation; only omitted dependencies use RDMO defaults."""
    if reader is None:
        reader = _build_reader(project, snapshot)
    if mapping is None:
        mapping = compute_metadata
    if serializer is None:
        serializer = compute_radar_payload
    if writer is None:
        # Import adapter-package defaults here so adapters can later import these factories.
        from .exports.storage import store_export_result
        writer = partial(store_export_result, project)
    kwargs = {} if clock is None else {'clock': clock}
    return RadarExportService(reader, mapping, serializer, writer, **kwargs)


def build_xml_export_service(
    project, *, snapshot=None, reader=None, mapping=None, serializer=None, renderer=None, validator=None,
):
    """Prepare XML export data once, without requiring RADAR provider settings."""
    if reader is None:
        reader = _build_reader(project, snapshot)
    if mapping is None:
        mapping = compute_metadata
    if serializer is None:
        serializer = to_xml_payload
    if renderer is None:
        from rdmo.core.exports import prettify_xml

        from .exports.renderers import RadarExportRenderer

        def renderer(payload):
            return prettify_xml(RadarExportRenderer().render(payload))
    if validator is None:
        from .exports.validation import get_radar_validation_errors
        validator = get_radar_validation_errors
    return RadarXmlExportService(reader, mapping, serializer, renderer, validator)


def build_import_service(
    import_plugin, *, set_index=None, existing_values=None, parser=None, mapping=None, writer=None,
):
    """Prepare unsaved import staging; an explicit writer replaces preparation entirely."""
    if parser is None:
        parser = parse_xml
    if writer is None:
        if existing_values is None:
            if import_plugin.current_project is None:
                raise ValueError('RADAR import requires an existing project.')
            existing_values = fetch_project_values(import_plugin.current_project)
        if set_index is None:
            set_index = compute_next_dataset_index(existing_values)
        if mapping is None:
            mapping = write_metadata
        writer = partial(mapping, import_plugin, set_index=set_index, existing_values=existing_values)
    return RadarImportService(parser, writer)
