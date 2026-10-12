"""Build operation-scoped services with mapping profiles and explicit overrides."""
from functools import partial

from .exceptions import UnsupportedImportMapping
from .mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING
from .metadata.api import compute_radar_payload
from .metadata.xml import parse_xml, to_xml_payload
from .services import RadarExportService, RadarImportService, RadarXmlExportService

_UNSET = object()


def build_export_service(
    project, *, snapshot=None, profile=None, reader=None, mapping=None, serializer=None,
    writer=_UNSET, clock=None,
):
    """Explicit dependencies win; an omitted profile retains legacy TF defaults."""
    if profile is None:
        profile = TEMPLATE_FRAMEWORK_MAPPING
    if reader is None:
        reader = profile.build_reader(project, snapshot=snapshot)
    if mapping is None:
        mapping = profile.compute_metadata
    if serializer is None:
        serializer = compute_radar_payload
    if writer is _UNSET:
        writer = partial(profile.store_result, project) if profile.store_result is not None else None
    kwargs = {} if clock is None else {'clock': clock}
    return RadarExportService(reader, mapping, serializer, writer, **kwargs)


def build_xml_export_service(
    project, *, snapshot=None, profile=None, reader=None, mapping=None, serializer=None,
    renderer=None, validator=None,
):
    if profile is None:
        profile = TEMPLATE_FRAMEWORK_MAPPING
    if reader is None:
        reader = profile.build_reader(project, snapshot=snapshot)
    if mapping is None:
        mapping = profile.compute_metadata
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
    import_plugin, *, profile=None, set_index=None, existing_values=None, parser=None,
    mapping=None, writer=None,
):
    """A profile owns destination/allocation rules; an explicit writer skips preparation."""
    if profile is None:
        profile = TEMPLATE_FRAMEWORK_MAPPING
    if parser is None:
        parser = parse_xml
    if writer is None:
        if profile.build_import_writer is None and mapping is None:
            raise UnsupportedImportMapping('The selected RADAR mapping does not support import.')
        if existing_values is None:
            if import_plugin.current_project is None:
                raise ValueError('RADAR import requires an existing project.')
            from .metadata.values import fetch_project_values
            existing_values = fetch_project_values(import_plugin.current_project)
        if profile.build_import_writer is not None:
            writer = profile.build_import_writer(import_plugin, set_index=set_index,
                                                 existing_values=existing_values, mapping=mapping)
        else:
            # An explicit custom mapping owns allocation; never borrow TF coordinates.
            writer = partial(mapping, import_plugin, set_index=set_index, existing_values=existing_values)
    return RadarImportService(parser, writer)
