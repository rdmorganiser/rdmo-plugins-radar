"""Merge project answers and stage unsaved Values for RDMO import preview/apply."""
from dataclasses import dataclass, field

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.imports import Import as ProjectImport
from rdmo.projects.models import Value

from .fields.contracts import Coordinates
from .types import MappingIssue
from .values import ModelKey, get_option_path, is_uri, model_key, normalize, prepare_values, selector_label


@dataclass
class ProjectWriteContext:
    """Merge prepared answers and stage unsaved Values for RDMO's import preview/apply workflow."""

    import_plugin: ProjectImport
    existing_values: dict
    coordinates: Coordinates
    namespace: str | None = None
    issues: list[MappingIssue] = field(default_factory=list)
    _values: dict = field(init=False, repr=False)
    _attributes: dict[str | int, Attribute | None] = field(default_factory=dict, init=False, repr=False)
    _options: dict[str | int, Option | None] = field(default_factory=dict, init=False, repr=False)
    _ambiguous_attributes: set[str] = field(default_factory=set, init=False, repr=False)
    _ambiguous_options: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self):
        # Copy the buckets: staging must not change the prepared project read.
        self._values = prepare_values(self.existing_values)
        for value in self.import_plugin.values:
            if value.attribute is not None:
                self._append_value(value)

    def _attribute_key(self, attribute):
        attribute_key = model_key(attribute)
        for existing_attribute_key in self._values:
            if existing_attribute_key.identity == attribute_key.identity:
                return existing_attribute_key
        if attribute_key.kind == 'object':
            # A synthetic import API destination can alias one prepared fixture bucket.
            matching_attribute_keys = [
                attribute_key for attribute_key in self._values if attribute_key.path == attribute.path
            ]
            if len(matching_attribute_keys) == 1:
                return matching_attribute_keys[0]
        return attribute_key

    def _append_value(self, value, *, resolved=False):
        attribute_key = self._attribute_key(value.attribute) if resolved else model_key(value.attribute)
        if not resolved:
            attribute_key = next(
                (
                    existing_attribute_key
                    for existing_attribute_key in self._values
                    if existing_attribute_key.identity == attribute_key.identity
                ),
                attribute_key,
            )
        synthetic_attribute_key = ModelKey('path', value.attribute.path, value.attribute.path, None)
        if attribute_key.kind == 'object' and synthetic_attribute_key in self._values:
            attribute_key = synthetic_attribute_key
        self._values.setdefault(attribute_key, []).append(value)

    def add(
        self,
        path: str,
        text: object,
        *,
        set_prefix: str | None = None,
        set_index: int | None = None,
        collection_index: int | None = None,
        external_id: str = '',
    ) -> Value | None:
        if text in (None, ''):
            return None
        attribute = self.fetch_attribute(path)
        if attribute is None:
            if path not in self._ambiguous_attributes:
                self.warn(path, 'RDMO Attribute is not installed', str(text))
            return None
        return self._add_value(
            attribute,
            text,
            set_prefix=set_prefix,
            set_index=set_index,
            collection_index=collection_index,
            external_id=external_id,
        )

    def add_option(
        self,
        path: str,
        canonical_value: str | None,
        options: dict[str, str],
        *,
        text: str | None = None,
        set_prefix: str | None = None,
        set_index: int | None = None,
        collection_index: int | None = None,
    ) -> Value | None:
        if canonical_value is None:
            return None
        option_reference = get_option_path(options, canonical_value)
        if option_reference is None:
            self.warn(path, 'RADAR controlled value has no RDMO mapping', canonical_value)
            return None
        attribute = self.fetch_attribute(path)
        option = self.fetch_option(option_reference)
        if attribute is None:
            if path not in self._ambiguous_attributes:
                self.warn(path, 'RDMO Attribute is not installed', canonical_value)
            return None
        if option is None:
            if option_reference not in self._ambiguous_options:
                self.warn(path, f'RDMO Option is not installed: {option_reference}', canonical_value)
            return None
        return self._add_value(
            attribute,
            text,
            option=option,
            set_prefix=set_prefix,
            set_index=set_index,
            collection_index=collection_index,
        )

    def add_unique_text(self, path: str, text: str, *, coordinates: Coordinates | None = None) -> Value | None:
        normalized = normalize(text)
        if any(normalize(value.text) == normalized for value in self.get_values(path)):
            return None
        position = coordinates if coordinates is not None else self.coordinates
        return self.add(path, text, collection_index=self.compute_next_collection_index(path),
                        set_prefix=position.set_prefix, set_index=position.set_index)

    def get_values(self, path) -> list[Value]:
        if isinstance(path, str):
            if not any((key.uri if is_uri(path) else key.path) == path for key in self._values):
                return []
        attribute = self.fetch_attribute(path)
        return list(self._values.get(self._attribute_key(attribute), ())) if attribute is not None else []

    def compute_next_set_index(self, anchor_path: str) -> int:
        attribute_values = self.get_values(anchor_path)
        return max((value.set_index for value in attribute_values), default=-1) + 1

    def compute_next_collection_index(self, path: str) -> int:
        attribute_values = self.get_values(path)
        return max((value.collection_index for value in attribute_values), default=-1) + 1

    def fetch_attribute(self, path) -> Attribute | None:
        return self._resolve_destination(
            path, model=Attribute, path_field='path', lookup=self.import_plugin.get_attribute,
            cache=self._attributes, ambiguous=self._ambiguous_attributes,
            validate=self._validate_attribute_destination,
        )

    def fetch_option(self, path) -> Option | None:
        return self._resolve_destination(
            path, model=Option, path_field='uri_path', lookup=self.import_plugin.get_option,
            cache=self._options, ambiguous=self._ambiguous_options,
        )

    def _validate_attribute_destination(self, path, attribute):
        # Attribute-only safeguard: a synthetic destination must identify one prepared bucket.
        if model_key(attribute).kind == 'object':
            if sum(key.path == attribute.path for key in self._values) > 1:
                self._ambiguous_attributes.add(path)
                self.warn(path, 'Ambiguous synthetic Attribute import destination')
                return None
        return attribute

    def _resolve_destination(self, path, *, model, path_field, lookup, cache, ambiguous, validate=None):
        """Resolve through the public import API, caching hits, misses and ambiguities per operation."""
        if isinstance(path, model):
            return path
        if path in cache:
            return cache[path]
        if isinstance(path, int):
            instance = model.objects.filter(pk=path).first()
            cache[path] = lookup(instance.uri) if instance else None
            return cache[path]
        if not path:
            cache[path] = None
            return None
        uri = path if is_uri(path) else model.build_uri(self.namespace, path) if self.namespace else None
        instance = lookup(uri) if uri else None
        # Preserve installed custom URI prefixes; full URIs never fall back to short paths.
        if instance is None and not is_uri(path):
            matches = {}
            for uri in model.objects.filter(**{path_field: path}).values_list('uri', flat=True):
                candidate = lookup(uri)
                if candidate is not None:
                    matches[model_key(candidate, getattr(candidate, path_field))] = candidate
            if len(matches) == 1:
                instance = next(iter(matches.values()))
            elif matches:
                ambiguous.add(path)
                self.warn(path, f'Ambiguous {model.__name__} import destination')
        if instance is not None and validate is not None:
            instance = validate(path, instance)
        cache[path] = instance
        return instance

    def _add_value(
        self,
        attribute: Attribute,
        text: object,
        *,
        option: Option | None = None,
        set_prefix: str | None = None,
        set_index: int | None = None,
        collection_index: int | None = None,
        external_id: str = '',
    ) -> Value:
        value = Value(
            attribute=attribute,
            option=option,
            set_prefix=self.coordinates.set_prefix if set_prefix is None else set_prefix,
            set_index=self.coordinates.set_index if set_index is None else set_index,
            text=text,
            external_id=external_id,
        )
        value.collection_index = self.coordinates.collection_index if collection_index is None else collection_index
        self.import_plugin.values.append(value)
        self._append_value(value, resolved=True)
        return value

    def warn(self, field: str, reason: str, value: str | None = None) -> None:
        issue = MappingIssue(selector_label(field), reason, value)
        if issue not in self.issues:
            self.issues.append(issue)
