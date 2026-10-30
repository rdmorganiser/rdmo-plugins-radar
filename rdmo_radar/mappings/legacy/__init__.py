"""Historical flat-coordinate exports using the shared RADAR services and serializers."""

from dataclasses import replace
from functools import partial

from ...metadata.builder import compute_metadata as compose_metadata
from ...metadata.fields import Source
from ...metadata.read_context import ProjectReadContext
from .. import ExportDataset, RadarMapping
from ..common.readers import prepare_project_read
from .fields import LEGACY_FIELDS, first_text, read_set


def select_values(context, attribute_key):
    """Legacy get_set reads one prefix; scalar getters use exact prefix/index pairs."""
    values = context.prepared.values.get(attribute_key, ())
    if context.scope == 'project':
        return list(values)
    return [value for value in values
            if (value.set_prefix, value.set_index) == (context.set_prefix, context.set_index)]


def build_reader(project, snapshot=None):
    values, placements, prepared = prepare_project_read(project, snapshot)
    root = ProjectReadContext(
        values, placements, prepared=prepared, project=project,
        value_selector=select_values,
    )

    def read(dataset):
        context = replace(root, issues=[])
        return context if dataset is None else context.group(dataset.scope['set_prefix'], dataset.scope['set_index'])

    return read


def get_datasets(project, reader):
    root = reader(None)
    datasets = []
    indices = set()
    for marker in read_set(root, 'project/dataset/id'):
        index = marker.set_index
        if index in indices:
            raise ValueError('Legacy dataset markers must have unique set indices at the empty prefix.')
        indices.add(index)
        context = root.group('', index)
        destinations = {}
        for name in ('radar_id', 'radar_url'):
            path = f'project/dataset/{name}'
            identities = context.prepared.lookup.get(('path', path), ())
            key = context.resolve_attribute(path)
            destinations[name] = (
                None if identities and key is None else {
                    **({'uri': key.uri} if key is not None else {'path': path}),
                    'set_prefix': '', 'set_index': index, 'collection_index': 0,
                }
            )
        datasets.append(ExportDataset(
            str(index), str(marker.value or f'Dataset #{index + 1}'),
            {'set_prefix': '', 'set_index': index, 'destinations': destinations},
            radar_url=first_text(context, source=Source('project/dataset/radar_url'), target=None),
            fallback_file_stem=str(index + 1),
        ))
    return datasets


def store_result(project, dataset, radar_id, radar_url):
    from ...exports.storage import store_export_result

    return store_export_result(
        project, dataset.scope['set_index'], radar_id, radar_url, destinations=dataset.scope['destinations'],
    )


compute_metadata = partial(compose_metadata, fields=LEGACY_FIELDS)
LEGACY_MAPPING = RadarMapping(get_datasets, build_reader, compute_metadata, store_result=store_result)
