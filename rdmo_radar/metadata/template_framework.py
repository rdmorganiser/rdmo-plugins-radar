"""Established Template Framework scope and allocation rules; no mapping profiles."""
from .values import coordinates, get_scoped_values, matches_placement, prepare_read_data

# Attributes used to discover dataset records and constrain their collection scope.
DATASET_ATTRIBUTES = ('project/dataset/id', 'project/dataset/title')

DEFAULT_URI_PREFIX = 'https://rdmorganiser.github.io/terms/'

# Attribute paths to RADAR field names in diagnostics; this does not validate scalar values.
ATTRIBUTE_TO_RADAR_FIELDS = {
    'project/dataset/title': 'title',
    'project/dataset/id': 'title',
    'project/dataset/description': 'resource',
    'project/dataset/pids/system': 'identifier.identifierType',
    'project/dataset/data_publication_pid': 'identifier',
    'project/dataset/language': 'language',
    'project/dataset/usage_technology/geo_location': 'geoLocations',
    'project/acronym': 'additionalTitles',
    'project/funder/name': 'fundingReferences.funderName',
    'project/funder/grant_nr': 'fundingReferences.awardNumber',
    'project/funder/programme/title': 'fundingReferences.awardTitle',
    'project/funder/programme/url': 'fundingReferences.awardURI',
}


def get_dataset_values(context, key):
    attribute_values_map, attribute_placements_map, attribute_lookup_map = context.prepared
    constraints = {
        anchor: context.set_index
        for attribute_path in DATASET_ATTRIBUTES
        for anchor in attribute_lookup_map.get(('path', attribute_path), ())
    }
    if attribute_placements_map.get(key):
        attribute_values = get_scoped_values(
            attribute_values_map, attribute_placements_map, key, constraints=constraints
        )
        if context.dataset_prefix is None:
            return attribute_values
        dataset_coordinates = tuple(context.dataset_prefix.split('|')) if context.dataset_prefix else ()
        return [
            value
            for value in attribute_values
            if any(
                matches_placement(value, placement, constraints)
                and all(
                    coordinates(value)[:level] == dataset_coordinates
                    for level, (anchor, _) in enumerate(placement)
                    if anchor in constraints
                )
                for placement in attribute_placements_map[key]
            )
        ]
    attribute_values = attribute_values_map.get(key, ())
    if key[2].startswith('project/dataset/creator/'):
        set_prefix = (
            f'{context.dataset_prefix}|{context.set_index}' if context.dataset_prefix else str(context.set_index)
        )
        return [
            value
            for value in attribute_values
            if value.set_prefix and coordinates(value)[: len(set_prefix.split('|'))] == tuple(set_prefix.split('|'))
        ]
    return [
        value
        for value in attribute_values
        if value.set_prefix == (context.dataset_prefix or '') and value.set_index == context.set_index
    ]


def compute_dataset_indices(context):
    attribute_values_map, attribute_placements_map, _ = context.prepared
    dataset_attribute_keys = {
        attribute_key
        for attribute_path in DATASET_ATTRIBUTES
        if (attribute_key := context.resolve_attribute(attribute_path)) is not None
    }
    set_indices = set()
    for attribute_key in dataset_attribute_keys:
        attribute_placements = attribute_placements_map.get(attribute_key, ())
        for value in get_scoped_values(attribute_values_map, attribute_placements_map, attribute_key):
            for placement in attribute_placements:
                if matches_placement(value, placement):
                    for level, (anchor, _) in enumerate(placement):
                        if anchor in dataset_attribute_keys:
                            set_indices.add(int(coordinates(value)[level]))
                            break
            if (
                not any(
                    anchor in dataset_attribute_keys
                    for placement in attribute_placements
                    for anchor, _ in placement
                )
                and not value.set_prefix
            ):
                set_indices.add(value.set_index)
    return sorted(set_indices)


def compute_next_dataset_index(values, import_plugin=None, *, context=None):
    """Allocate after current titles, scoped to the resolved import destination."""
    if context is not None:
        attribute_values = context.get_values('project/dataset/title')
    elif import_plugin is not None:
        from .write_context import ProjectWriteContext

        attribute_values = ProjectWriteContext(import_plugin, 0, values).get_values('project/dataset/title')
    else:
        attribute_values_map, _, attribute_lookup_map = prepare_read_data(values, {})
        attribute_keys = attribute_lookup_map.get(('path', 'project/dataset/title'), ())
        attribute_values = attribute_values_map.get(attribute_keys[0], ()) if len(attribute_keys) == 1 else ()
    return max((value.set_index for value in attribute_values), default=-1) + 1
