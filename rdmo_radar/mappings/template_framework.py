"""The established Template Framework export/import mapping and scope conventions."""
from functools import partial

from ..metadata.builder import compute_metadata
from ..metadata.importer import write_metadata
from ..metadata.rdmo import RDMOReadContext, RDMOWriteContext
from ..metadata.template_framework import DATASET_ANCHORS, compute_next_dataset_index
from ..metadata.values import (
    coordinates,
    fetch_catalog_placements,
    fetch_project_values,
    get_scoped_values,
    matches_placement,
    prepare_read_data,
)
from . import ExportCandidate, RadarMapping


def build_reader(project, snapshot=None):
    values = fetch_project_values(project, snapshot)
    placements = fetch_catalog_placements(project.catalog)
    prepared = prepare_read_data(values, placements)

    def read(candidate):
        if isinstance(candidate, ExportCandidate):
            prefix = candidate.scope['set_prefix']
            index = candidate.scope['set_index']
        else:
            prefix, index = None, int(candidate)
        return RDMOReadContext(values, placements, set_index=index, dataset_prefix=prefix, prepared=prepared)

    return read


def get_datasets(project, reader):
    context = reader(0)
    values, placements, _ = context.prepared
    anchors = {key for path in DATASET_ANCHORS if (key := context.resolve_attribute(path)) is not None}
    positions = set()
    for key in anchors:
        scopes = placements.get(key, ())
        for value in get_scoped_values(values, placements, key):
            for placement in scopes:
                if matches_placement(value, placement):
                    for level, (anchor, _) in enumerate(placement):
                        if anchor in anchors:
                            position = coordinates(value)
                            positions.add(('|'.join(position[:level]), int(position[level])))
                            break
            if not any(anchor in anchors for scope in scopes for anchor, _ in scope) and not value.set_prefix:
                positions.add(('', value.set_index))
    candidates = []
    for prefix, index in sorted(positions, key=lambda position: (tuple(map(int, position[0].split('|')))
                                                               if position[0] else (), position[1])):
        key = f'dataset:{prefix}|{index}' if prefix else str(index)
        candidate = ExportCandidate(key, f'Dataset #{index + 1}', {'set_prefix': prefix, 'set_index': index})
        selected = reader(candidate)
        title = selected.get_text('project/dataset/title') or selected.get_text('project/dataset/id')
        scope = {**candidate.scope, 'destinations': result_destinations(selected)}
        candidates.append(ExportCandidate(key, title or candidate.label, scope,
                                          selected.get_text('project/dataset/radar_url'), str(index + 1)))
    return candidates


def result_destinations(context):
    """Capture exact installed catalog identities and scalar coordinates for callbacks."""
    _, placements, aliases = context.prepared
    destinations = {}
    for name in ('radar_id', 'radar_url'):
        path = f'project/dataset/{name}'
        keys = aliases.get(('path', path), ())
        if not keys:
            continue  # Retain installed path resolution for fields absent from prepared data.
        key = context.resolve_attribute(path)
        if key is None:
            destinations[name] = None  # Ambiguity must not enable an installed-path fallback.
            continue
        positions = set()
        for placement in placements.get(key, ()):
            for level, (anchor, _) in enumerate(placement):
                if anchor is not None and anchor[2] in DATASET_ANCHORS:
                    prefix = context.dataset_prefix.split('|') if context.dataset_prefix else []
                    if level != len(prefix) or any(collection for _, collection in placement[level + 1:]):
                        continue
                    position = [*prefix, str(context.set_index), *('0' for _ in placement[level + 1:])]
                    if all(collection or coordinate == '0'
                           for coordinate, (_, collection) in zip(position, placement, strict=True)):
                        positions.add(('|'.join(position[:-1]), int(position[-1])))
                    break
        if not placements.get(key):
            positions.add((context.dataset_prefix or '', context.set_index))
        if len(positions) != 1:
            destinations[name] = None
            continue
        prefix, index = positions.pop()
        destinations[name] = {'uri': key[3], 'set_prefix': prefix, 'set_index': index}
    return destinations


def store_result(project, candidate, radar_id, radar_url):
    # Keep registered adapter imports out of mapping construction.
    from ..exports.storage import store_export_result
    if isinstance(candidate, ExportCandidate):
        return store_export_result(project, candidate.scope['set_index'], radar_id, radar_url,
                                   set_prefix=candidate.scope['set_prefix'],
                                   destinations=candidate.scope.get('destinations'))
    return store_export_result(project, candidate, radar_id, radar_url)


def build_import_writer(import_plugin, *, set_index=None, existing_values, mapping=None):
    if mapping is None:
        mapping = write_metadata
    kwargs = {}
    if mapping is write_metadata:
        context = RDMOWriteContext(import_plugin, 0 if set_index is None else set_index, existing_values)
        if set_index is None:
            set_index = compute_next_dataset_index(existing_values, context=context)
            context.dataset_index = set_index
        kwargs['context'] = context
    elif set_index is None:
        set_index = compute_next_dataset_index(existing_values, import_plugin)
    return partial(mapping, import_plugin, set_index=set_index, existing_values=existing_values, **kwargs)


TEMPLATE_FRAMEWORK_MAPPING = RadarMapping(get_datasets, build_reader, compute_metadata,
                                        build_import_writer, store_result)
