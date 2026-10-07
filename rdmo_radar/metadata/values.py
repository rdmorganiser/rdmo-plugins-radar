"""Resolve stored answers using the catalog's page/questionset coordinates."""
from collections import defaultdict

DATASET_ANCHORS = {'project/dataset/id', 'project/dataset/title'}


def coordinates(value):
    return (*value.set_prefix.split('|'), str(value.set_index)) if value.set_prefix else (str(value.set_index),)


class AnswerIndex:
    def __init__(self, export):
        self.values = defaultdict(list)
        self.placements = defaultdict(list)
        for value in export.project.values.filter(snapshot=export.snapshot).select_related('attribute', 'option'):
            if value.attribute:
                self.values[value.attribute.path].append(value)
        for values in self.values.values():
            values.sort(key=lambda value: (tuple(int(part) for part in coordinates(value)), value.collection_index))
        catalog = getattr(export.project, 'catalog', None)
        if catalog:
            catalog.prefetch_elements()
            self._walk(catalog)

    def _walk(self, element, ancestors=()):
        kind = element._meta.model_name
        attribute = getattr(element, 'attribute', None)
        path = attribute.path if attribute else None
        if kind in ('page', 'questionset'):
            ancestors = (*ancestors, (path, element.is_collection))
        if path:
            self.placements[path].append(ancestors)
        for child in getattr(element, 'elements', ()):
            self._walk(child, ancestors)

    def rows(self, path, dataset_index=None, group=None):
        values = self.values.get(path, [])
        if group is not None:
            return [value for value in values if (value.set_prefix, value.set_index) == group]
        placements = self.placements.get(path)
        if placements:
            return [value for value in values if any(
                self._matches(value, placement, dataset_index) for placement in placements
            )]
        if dataset_index is None:
            return list(values)
        # Legacy attributes absent from the catalog retain their established layout.
        if path.startswith('project/dataset/creator/'):
            return [value for value in values if coordinates(value)[0] == str(dataset_index) and value.set_prefix]
        return [value for value in values if value.set_prefix == '' and value.set_index == dataset_index]

    @staticmethod
    def _matches(value, placement, dataset_index):
        position = coordinates(value)
        if len(position) != len(placement):
            return False
        for coordinate, (anchor, collection) in zip(position, placement, strict=True):
            if not collection and coordinate != '0':
                return False
            if anchor in DATASET_ANCHORS and dataset_index is not None and coordinate != str(dataset_index):
                return False
        return True

    def dataset_indices(self):
        indices = set()
        for path in DATASET_ANCHORS:
            for value in self.rows(path):
                placements = self.placements.get(path, [])
                for placement in placements:
                    if self._matches(value, placement, None):
                        for level, (anchor, _) in enumerate(placement):
                            if anchor in DATASET_ANCHORS:
                                indices.add(int(coordinates(value)[level]))
                                break
                if not any(anchor in DATASET_ANCHORS for p in placements for anchor, _ in p) and not value.set_prefix:
                    indices.add(value.set_index)
        return sorted(indices)


def get_answer_index(export):
    """Cache the single production read path for this project/snapshot."""
    project = export.project
    key = (id(project), getattr(export, 'snapshot', None))
    cached = getattr(export, '_radar_answer_index', None)
    if cached is None or cached[0] != key:
        cached = (key, AnswerIndex(export))
        export._radar_answer_index = cached
    return cached[1]
