"""The established Template Framework export/import mapping and scope conventions."""
from functools import partial

from ..metadata.builder import compute_metadata
from ..metadata.importer import write_metadata
from ..metadata.read_context import ProjectReadContext
from ..metadata.template_framework import DATASET_ATTRIBUTES, compute_next_dataset_index
from ..metadata.values import (
    coordinates,
    fetch_catalog_placements,
    fetch_project_values,
    get_scoped_values,
    matches_placement,
    prepare_read_data,
)
from ..metadata.write_context import ProjectWriteContext
from . import ExportDataset, RadarMapping


def build_reader(project, snapshot=None):
    attribute_values_map = fetch_project_values(project, snapshot)
    attribute_placements_map = fetch_catalog_placements(project.catalog)
    prepared = prepare_read_data(attribute_values_map, attribute_placements_map)

    def read(dataset):
        if isinstance(dataset, ExportDataset):
            set_prefix = dataset.scope['set_prefix']
            set_index = dataset.scope['set_index']
        else:
            set_prefix, set_index = None, int(dataset)
        return ProjectReadContext(
            attribute_values_map,
            attribute_placements_map,
            set_index=set_index,
            dataset_prefix=set_prefix,
            prepared=prepared,
        )

    return read


def get_datasets(project, reader):
    context = reader(0)
    attribute_values_map, attribute_placements_map, _ = context.prepared
    dataset_attribute_keys = {
        attribute_key
        for attribute_path in DATASET_ATTRIBUTES
        if (attribute_key := context.resolve_attribute(attribute_path)) is not None
    }
    set_positions = set()
    for attribute_key in dataset_attribute_keys:
        attribute_placements = attribute_placements_map.get(attribute_key, ())
        for value in get_scoped_values(attribute_values_map, attribute_placements_map, attribute_key):
            for placement in attribute_placements:
                if matches_placement(value, placement):
                    for level, (anchor, _) in enumerate(placement):
                        if anchor in dataset_attribute_keys:
                            position = coordinates(value)
                            set_positions.add(('|'.join(position[:level]), int(position[level])))
                            break
            if (
                not any(
                    anchor in dataset_attribute_keys
                    for placement in attribute_placements
                    for anchor, _ in placement
                )
                and not value.set_prefix
            ):
                set_positions.add(('', value.set_index))
    datasets = []
    for set_prefix, set_index in sorted(
        set_positions,
        key=lambda position: (tuple(map(int, position[0].split('|'))) if position[0] else (), position[1]),
    ):
        dataset_key = f'dataset:{set_prefix}|{set_index}' if set_prefix else str(set_index)
        dataset = ExportDataset(
            dataset_key, f'Dataset #{set_index + 1}', {'set_prefix': set_prefix, 'set_index': set_index}
        )
        selected = reader(dataset)
        title = selected.get_text('project/dataset/title') or selected.get_text('project/dataset/id')
        dataset_scope = {**dataset.scope, 'destinations': result_destinations(selected)}
        datasets.append(
            ExportDataset(
                dataset_key,
                title or dataset.label,
                dataset_scope,
                selected.get_text('project/dataset/radar_url'),
                str(set_index + 1),
            )
        )
    return datasets


def result_destinations(context):
    """Capture exact installed catalog identities and scalar coordinates for callbacks."""
    _, attribute_placements_map, attribute_lookup_map = context.prepared
    destinations = {}
    for name in ('radar_id', 'radar_url'):
        attribute_path = f'project/dataset/{name}'
        attribute_keys = attribute_lookup_map.get(('path', attribute_path), ())
        if not attribute_keys:
            continue  # Retain installed path resolution for fields absent from prepared data.
        attribute_key = context.resolve_attribute(attribute_path)
        if attribute_key is None:
            destinations[name] = None  # Ambiguity must not enable an installed-path fallback.
            continue
        set_positions = set()
        for placement in attribute_placements_map.get(attribute_key, ()):
            for level, (anchor, _) in enumerate(placement):
                if anchor is not None and anchor[2] in DATASET_ATTRIBUTES:
                    set_prefix_parts = context.dataset_prefix.split('|') if context.dataset_prefix else []
                    if level != len(set_prefix_parts) or any(collection for _, collection in placement[level + 1 :]):
                        continue
                    position = [*set_prefix_parts, str(context.set_index), *('0' for _ in placement[level + 1 :])]
                    if all(
                        collection or coordinate == '0'
                        for coordinate, (_, collection) in zip(position, placement, strict=True)
                    ):
                        set_positions.add(('|'.join(position[:-1]), int(position[-1])))
                    break
        if not attribute_placements_map.get(attribute_key):
            set_positions.add((context.dataset_prefix or '', context.set_index))
        if len(set_positions) != 1:
            destinations[name] = None
            continue
        set_prefix, set_index = set_positions.pop()
        destinations[name] = {'uri': attribute_key[3], 'set_prefix': set_prefix, 'set_index': set_index}
    return destinations


def store_result(project, dataset, radar_id, radar_url):
    # Keep registered adapter imports out of mapping construction.
    from ..exports.storage import store_export_result

    if isinstance(dataset, ExportDataset):
        return store_export_result(
            project,
            dataset.scope['set_index'],
            radar_id,
            radar_url,
            set_prefix=dataset.scope['set_prefix'],
            destinations=dataset.scope.get('destinations'),
        )
    return store_export_result(project, dataset, radar_id, radar_url)


def build_import_writer(import_plugin, *, set_index=None, existing_values, mapping=None):
    if mapping is None:
        mapping = write_metadata
    kwargs = {}
    if mapping is write_metadata:
        context = ProjectWriteContext(import_plugin, 0 if set_index is None else set_index, existing_values)
        if set_index is None:
            set_index = compute_next_dataset_index(existing_values, context=context)
            context.dataset_index = set_index
        kwargs['context'] = context
    elif set_index is None:
        set_index = compute_next_dataset_index(existing_values, import_plugin)
    return partial(mapping, import_plugin, set_index=set_index, existing_values=existing_values, **kwargs)


TEMPLATE_FRAMEWORK_MAPPING = RadarMapping(
    get_datasets, build_reader, compute_metadata, build_import_writer, store_result
)
