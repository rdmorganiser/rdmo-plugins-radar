"""Prepare native RDMO Values and match coordinates without catalog-specific paths."""
from collections import defaultdict
from urllib.parse import urlsplit

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
    prepared = defaultdict(list)
    identities = {}
    for source, answers in values.items():
        if isinstance(source, tuple):
            prepared[identities.setdefault(source[:2], source)].extend(answers)
            continue
        for value in answers:
            attribute = getattr(value, 'attribute', None)
            if attribute is None and not isinstance(source, str):
                continue
            key = model_key(attribute) if attribute is not None else ('path', source, source, None)
            if key[0] == 'object' and isinstance(source, str):
                key = ('path', source, source, None)
            key = identities.setdefault(key[:2], key)
            prepared[key].append(value)
    return dict(prepared)


def prepare_read_data(values, placements):
    """Prepare buckets and local aliases once, including attributes with no answers."""
    values = prepare_values(values)
    identities = {key[:2]: key for key in values}
    paths = defaultdict(set)
    for key in values:
        paths[key[2]].add(key)

    def placement_key(key):
        if not isinstance(key, str):
            # Catalog prefetch objects may have stale URI labels. The PK still identifies
            # the same Attribute; prefer labels from freshly prepared Value relations.
            return identities.setdefault(key[:2], key)
        matches = paths[key]
        # Do not assign a path-only placement to one of several identifiable Attributes.
        return next(iter(matches)) if len(matches) == 1 else ('path', key, key, None)

    prepared_placements = defaultdict(list)
    for key, scopes in placements.items():
        prepared_placements[placement_key(key)].extend(
            tuple((placement_key(anchor) if anchor is not None else None, collection)
                  for anchor, collection in scope)
            for scope in scopes
        )
    aliases = defaultdict(set)
    keys = set(values) | set(prepared_placements)
    keys.update(anchor for scopes in prepared_placements.values() for scope in scopes
                for anchor, _ in scope if anchor is not None)
    for key in keys:
        aliases[('path', key[2])].add(key)
        aliases[key[:2]].add(key)
        if key[3]:
            aliases[('uri', key[3])].add(key)
    return values, dict(prepared_placements), {alias: tuple(keys) for alias, keys in aliases.items()}


def coordinates(value):
    return (*value.set_prefix.split('|'), str(value.set_index)) if value.set_prefix else (str(value.set_index),)


def fetch_project_values(project, snapshot=None):
    """Load Values and their Attributes/Options once, grouped by Attribute identity."""
    values = defaultdict(list)
    for value in project.values.filter(snapshot=snapshot).select_related('attribute', 'option'):
        if value.attribute is not None:
            values[model_key(value.attribute)].append(value)
    for answers in values.values():
        answers.sort(key=lambda value: (tuple(int(part) for part in coordinates(value)), value.collection_index))
    return dict(values)


def fetch_catalog_placements(catalog):
    """Convert core preorder to identity-aware ancestry, retaining empty markers."""
    placements = defaultdict(set)
    if catalog is not None:
        catalog.prefetch_elements()
        for page in catalog.pages:
            parents = defaultdict(set, {page: {()}})
            for element in (page, *page.descendants):
                attribute = getattr(element, 'attribute', None)
                key = model_key(attribute) if attribute is not None else None
                for ancestors in tuple(parents[element]):
                    scope = (*ancestors, (key, element.is_collection)) if isinstance(
                        element, Page | QuestionSet
                    ) else ancestors
                    if key is not None:
                        placements[key].add(scope)
                    for child in getattr(element, 'elements', ()):
                        parents[child].add(scope)
    return {key: tuple(scopes) for key, scopes in placements.items()}


def matches_placement(value, placement, constraints=None):
    """Match complete coordinates and explicit identity-based scope constraints."""
    constraints = constraints or {}
    position = coordinates(value)
    return len(position) == len(placement) and all(
        (collection or coordinate == '0') and
        (anchor not in constraints or coordinate == str(constraints[anchor]))
        for coordinate, (anchor, collection) in zip(position, placement, strict=True)
    )


def get_scoped_values(values, placements, key, *, constraints=None, group=None):
    answers = values.get(key, ())
    if group is not None:
        return [value for value in answers if (value.set_prefix, value.set_index) == group]
    if placements.get(key):
        return [value for value in answers if any(
            matches_placement(value, placement, constraints) for placement in placements[key]
        )]
    return list(answers)
