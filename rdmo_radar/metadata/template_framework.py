"""Established Template Framework scope and allocation rules; no mapping profiles."""
from .values import coordinates, get_scoped_values, matches_placement, prepare_read_data

DATASET_ANCHORS = ('project/dataset/id', 'project/dataset/title')

TERMS_PREFIX = 'https://rdmorganiser.github.io/terms/domain/'
OPTION_PREFIXES = (
    'https://rdmorganiser.github.io/terms/options/',
    'https://rdmo.jochenklar.dev/terms/options/',
)

SCALAR_TARGETS = {
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
    values, placements, aliases = context.prepared
    constraints = {anchor: context.set_index for path in DATASET_ANCHORS
                   for anchor in aliases.get(('path', path), ())}
    if placements.get(key):
        answers = get_scoped_values(values, placements, key, constraints=constraints)
        if context.dataset_prefix is None:
            return answers
        prefix = tuple(context.dataset_prefix.split('|')) if context.dataset_prefix else ()
        return [value for value in answers if any(
            matches_placement(value, placement, constraints) and all(
                coordinates(value)[:level] == prefix
                for level, (anchor, _) in enumerate(placement) if anchor in constraints
            ) for placement in placements[key]
        )]
    answers = values.get(key, ())
    if key[2].startswith('project/dataset/creator/'):
        prefix = f'{context.dataset_prefix}|{context.set_index}' if context.dataset_prefix else str(context.set_index)
        return [value for value in answers if value.set_prefix and
                coordinates(value)[:len(prefix.split('|'))] == tuple(prefix.split('|'))]
    return [value for value in answers if value.set_prefix == (context.dataset_prefix or '')
            and value.set_index == context.set_index]


def compute_dataset_indices(context):
    values, placements, _ = context.prepared
    anchors = {key for path in DATASET_ANCHORS if (key := context.resolve_attribute(path)) is not None}
    indices = set()
    for key in anchors:
        scopes = placements.get(key, ())
        for value in get_scoped_values(values, placements, key):
            for placement in scopes:
                if matches_placement(value, placement):
                    for level, (anchor, _) in enumerate(placement):
                        if anchor in anchors:
                            indices.add(int(coordinates(value)[level]))
                            break
            if not any(anchor in anchors for scope in scopes for anchor, _ in scope) and not value.set_prefix:
                indices.add(value.set_index)
    return sorted(indices)


def compute_next_dataset_index(values, import_plugin=None, *, context=None):
    """Allocate after current titles, scoped to the resolved import destination."""
    if context is not None:
        answers = context.get_values('project/dataset/title')
    elif import_plugin is not None:
        from .rdmo import RDMOWriteContext
        answers = RDMOWriteContext(import_plugin, 0, values).get_values('project/dataset/title')
    else:
        prepared, _, aliases = prepare_read_data(values, {})
        keys = aliases.get(('path', 'project/dataset/title'), ())
        answers = prepared.get(keys[0], ()) if len(keys) == 1 else ()
    return max((value.set_index for value in answers), default=-1) + 1
