"""Prepare native RDMO answers and bridge the core's missing coordinate scopes.

See docs/architecture.md for the public API audit and minimized core gaps.
"""
from collections import defaultdict

from rdmo.questions.models import Page, QuestionSet

DATASET_ANCHORS = ('project/dataset/id', 'project/dataset/title')


def compute_next_dataset_index(values):
    """Allocate after persisted dataset titles, preserving the import convention."""
    current_datasets = values.get('project/dataset/title', ())
    return max((value.set_index for value in current_datasets), default=-1) + 1


def coordinates(value):
    return (*value.set_prefix.split('|'), str(value.set_index)) if value.set_prefix else (str(value.set_index),)


def fetch_project_values(project, snapshot=None):
    """Load Values once; group by native path without imposing a catalog or namespace."""
    values = defaultdict(list)
    for value in project.values.filter(snapshot=snapshot).select_related('attribute', 'option'):
        if value.attribute:
            values[value.attribute.path].append(value)
    for answers in values.values():
        answers.sort(key=lambda value: (tuple(int(part) for part in coordinates(value)), value.collection_index))
    return dict(values)


def fetch_catalog_placements(catalog):
    """Convert core model preorder to minimal coordinate ancestry, including empty markers.

    RDMO exposes descendants/links but no public placement API. The temporary parent scopes
    preserve reused elements; all recursive traversal and model loading belong to core.
    """
    placements = defaultdict(set)
    if catalog is not None:
        catalog.prefetch_elements()
        for page in catalog.pages:
            parents = defaultdict(set, {page: {()}})
            for element in (page, *page.descendants):
                attribute = getattr(element, 'attribute', None)
                path = attribute.path if attribute else None
                for ancestors in tuple(parents[element]):
                    scope = (*ancestors, (path, element.is_collection)) if isinstance(
                        element, Page | QuestionSet
                    ) else ancestors
                    if path:
                        placements[path].add(scope)
                    for child in getattr(element, 'elements', ()):
                        parents[child].add(scope)
    return {path: tuple(scopes) for path, scopes in placements.items()}


def matches_placement(value, placement, dataset_index=None):
    """Match complete coordinates; core filter_set's startswith is not boundary-safe."""
    position = coordinates(value)
    return len(position) == len(placement) and all(
        (collection or coordinate == '0') and
        (anchor not in DATASET_ANCHORS or dataset_index is None or coordinate == str(dataset_index))
        for coordinate, (anchor, collection) in zip(position, placement, strict=True)
    )


def get_scoped_values(values, placements, path, dataset_index=None, group=None):
    answers = values.get(path, ())
    if group is not None:
        return [value for value in answers if (value.set_prefix, value.set_index) == group]
    if placements.get(path):
        return [value for value in answers if any(
            matches_placement(value, placement, dataset_index) for placement in placements[path]
        )]
    if dataset_index is None:
        return list(answers)
    # Preserve only the established fallback for attributes absent from the catalog.
    if path.startswith('project/dataset/creator/'):
        return [value for value in answers if value.set_prefix and coordinates(value)[0] == str(dataset_index)]
    return [value for value in answers if value.set_prefix == '' and value.set_index == dataset_index]


def compute_dataset_indices(values, placements):
    indices = set()
    for path in DATASET_ANCHORS:
        scopes = placements.get(path, ())
        for value in get_scoped_values(values, placements, path):
            for placement in scopes:
                if matches_placement(value, placement):
                    for level, (anchor, _) in enumerate(placement):
                        if anchor in DATASET_ANCHORS:
                            indices.add(int(coordinates(value)[level]))
                            break
            if not any(anchor in DATASET_ANCHORS for scope in scopes for anchor, _ in scope) and not value.set_prefix:
                indices.add(value.set_index)
    return sorted(indices)
