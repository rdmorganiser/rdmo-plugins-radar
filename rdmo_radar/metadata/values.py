"""Prepare native Values, match coordinates, and format answers without catalog-specific paths."""
from collections import defaultdict
from urllib.parse import urlsplit

from django.utils.html import strip_tags

from rdmo.projects.models import Value
from rdmo.questions.models import Page, QuestionSet


def model_key(model, path=None):
    """An identity plus lookup labels; unsaved objects never share a None identity."""
    path = path if path is not None else model.path
    uri = model.uri or None
    if model.pk is not None:
        return ('id', model.pk, path, uri)
    if uri:
        return ('uri', uri, path, uri)
    return ('object', id(model), path, None)


def is_uri(selector):
    return isinstance(selector, str) and bool(urlsplit(selector).scheme)


def selector_key(selector):
    if isinstance(selector, int):
        return ('id', selector)
    if isinstance(selector, str):
        return ('uri' if is_uri(selector) else 'path', selector)
    if selector.pk is not None:
        return ('id', selector.pk)
    return model_key(selector)[:2]


def selector_label(selector):
    """Describe a selector without loading deferred fields on persisted models."""
    if isinstance(selector, str | int):
        return str(selector)
    if selector.pk is not None:
        return str(selector.pk)
    return selector.uri or selector.path or str(id(selector))


def prepare_values(values):
    """Adapt legacy path buckets, preserving each identifiable Attribute separately.

    A path-keyed bucket of path-only synthetic models explicitly represents one fixture
    Attribute. Outside that compatibility input, URI-less unsaved objects keep object identity.
    """
    attribute_values_map = defaultdict(list)
    attribute_identity_map = {}
    for attribute_reference, attribute_values in values.items():
        if isinstance(attribute_reference, tuple):
            attribute_key = attribute_identity_map.setdefault(attribute_reference[:2], attribute_reference)
            attribute_values_map[attribute_key].extend(attribute_values)
            continue
        for value in attribute_values:
            attribute = getattr(value, 'attribute', None)
            if attribute is None and not isinstance(attribute_reference, str):
                continue
            attribute_key = (
                model_key(attribute)
                if attribute is not None
                else ('path', attribute_reference, attribute_reference, None)
            )
            if attribute_key[0] == 'object' and isinstance(attribute_reference, str):
                attribute_key = ('path', attribute_reference, attribute_reference, None)
            attribute_key = attribute_identity_map.setdefault(attribute_key[:2], attribute_key)
            attribute_values_map[attribute_key].append(value)
    return dict(attribute_values_map)


def prepare_read_data(values, placements):
    """Prepare buckets and local aliases once, including attributes with no answers."""
    attribute_values_map = prepare_values(values)
    attribute_identity_map = {attribute_key[:2]: attribute_key for attribute_key in attribute_values_map}
    attribute_paths_map = defaultdict(set)
    for attribute_key in attribute_values_map:
        attribute_paths_map[attribute_key[2]].add(attribute_key)

    def placement_key(attribute_reference):
        if not isinstance(attribute_reference, str):
            # Catalog prefetch objects may have stale URI labels. The PK still identifies
            # the same Attribute; prefer labels from freshly prepared Value relations.
            return attribute_identity_map.setdefault(attribute_reference[:2], attribute_reference)
        matches = attribute_paths_map[attribute_reference]
        # Do not assign a path-only placement to one of several identifiable Attributes.
        return next(iter(matches)) if len(matches) == 1 else ('path', attribute_reference, attribute_reference, None)

    attribute_placements_map = defaultdict(list)
    for attribute_reference, attribute_placements in placements.items():
        attribute_placements_map[placement_key(attribute_reference)].extend(
            tuple(
                (placement_key(anchor) if anchor is not None else None, is_collection)
                for anchor, is_collection in placement
            )
            for placement in attribute_placements
        )
    attribute_lookup_map = defaultdict(set)
    attribute_keys = set(attribute_values_map) | set(attribute_placements_map)
    attribute_keys.update(
        anchor
        for attribute_placements in attribute_placements_map.values()
        for placement in attribute_placements
        for anchor, _ in placement
        if anchor is not None
    )
    for attribute_key in attribute_keys:
        attribute_lookup_map[('path', attribute_key[2])].add(attribute_key)
        attribute_lookup_map[attribute_key[:2]].add(attribute_key)
        if attribute_key[3]:
            attribute_lookup_map[('uri', attribute_key[3])].add(attribute_key)
    return (
        attribute_values_map,
        dict(attribute_placements_map),
        {
            attribute_reference: tuple(attribute_keys)
            for attribute_reference, attribute_keys in attribute_lookup_map.items()
        },
    )


def coordinates(value):
    return (*value.set_prefix.split('|'), str(value.set_index)) if value.set_prefix else (str(value.set_index),)


def fetch_project_values(project, snapshot=None):
    """Load Values and their Attributes/Options once, grouped by Attribute identity."""
    attribute_values_map = defaultdict(list)
    for value in project.values.filter(snapshot=snapshot).select_related('attribute', 'option'):
        if value.attribute is not None:
            attribute_values_map[model_key(value.attribute)].append(value)
    for attribute_values in attribute_values_map.values():
        attribute_values.sort(
            key=lambda value: (tuple(int(part) for part in coordinates(value)), value.collection_index)
        )
    return dict(attribute_values_map)


def fetch_catalog_placements(catalog):
    """Convert core preorder to identity-aware ancestry, retaining empty markers."""
    attribute_placements_map = defaultdict(set)
    if catalog is not None:
        catalog.prefetch_elements()
        for page in catalog.pages:
            parents = defaultdict(set, {page: {()}})
            for element in (page, *page.descendants):
                attribute = getattr(element, 'attribute', None)
                attribute_key = model_key(attribute) if attribute is not None else None
                for ancestors in tuple(parents[element]):
                    placement = (
                        (*ancestors, (attribute_key, element.is_collection))
                        if isinstance(element, Page | QuestionSet)
                        else ancestors
                    )
                    if attribute_key is not None:
                        attribute_placements_map[attribute_key].add(placement)
                    for child in getattr(element, 'elements', ()):
                        parents[child].add(placement)
    return {
        attribute_key: tuple(attribute_placements)
        for attribute_key, attribute_placements in attribute_placements_map.items()
    }


def matches_placement(value, placement, constraints=None):
    """Match complete coordinates and explicit identity-based scope constraints."""
    constraints = constraints or {}
    position = coordinates(value)
    return len(position) == len(placement) and all(
        (is_collection or coordinate == '0') and (anchor not in constraints or coordinate == str(constraints[anchor]))
        for coordinate, (anchor, is_collection) in zip(position, placement, strict=True)
    )


def get_scoped_values(values, placements, key, *, constraints=None, group=None):
    attribute_values = values.get(key, ())
    if group is not None:
        return [value for value in attribute_values if (value.set_prefix, value.set_index) == group]
    if placements.get(key):
        return [
            value
            for value in attribute_values
            if any(matches_placement(value, placement, constraints) for placement in placements[key])
        ]
    return list(attribute_values)


def select_values(context, attribute_key):
    """Select project or group Values using their prepared catalog placements."""
    attribute_values_map, attribute_placements_map, _ = context.prepared
    return get_scoped_values(
        attribute_values_map,
        attribute_placements_map,
        attribute_key,
        group=(context.set_prefix, context.set_index) if context.scope == 'group' else None,
    )


def get_option_path(options: dict[str, str], canonical_value: str) -> str | None:
    return next((option_reference for option_reference, value in options.items() if value == canonical_value), None)



def normalize(value: object) -> str:
    return ' '.join(str(value).split()).casefold()



def answer_label(value: Value) -> str:
    """Read option labels without Value.value's rendered display HTML."""
    label = strip_tags(str(value.option.text)) if value.option else ''
    text = value.text.strip() if value.text else ''
    return f'{label}: {text}' if label and text and label != text else text or label
