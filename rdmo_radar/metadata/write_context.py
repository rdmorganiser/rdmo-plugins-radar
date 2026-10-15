"""Merge project answers and stage unsaved Values for RDMO import preview/apply."""
from dataclasses import dataclass, field

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.imports import Import as ProjectImport
from rdmo.projects.models import Value

from .template_framework import DEFAULT_URI_PREFIX
from .types import MappingIssue
from .values import get_option_path, is_uri, model_key, normalize, prepare_values


@dataclass
class ProjectWriteContext:
    """Merge prepared answers and stage unsaved Values for RDMO's import preview/apply workflow."""

    import_plugin: ProjectImport
    dataset_index: int
    existing_values: dict
    issues: list[MappingIssue] = field(default_factory=list)
    _values: dict = field(init=False, repr=False)
    _attributes: dict[str, Attribute | None] = field(default_factory=dict, init=False, repr=False)
    _options: dict[str, Option | None] = field(default_factory=dict, init=False, repr=False)
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
            if existing_attribute_key[:2] == attribute_key[:2]:
                return existing_attribute_key
        if attribute_key[0] == 'object':
            # A synthetic import API destination can alias one prepared fixture bucket.
            matching_attribute_keys = [
                attribute_key for attribute_key in self._values if attribute_key[2] == attribute.path
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
                    if existing_attribute_key[:2] == attribute_key[:2]
                ),
                attribute_key,
            )
        synthetic_attribute_key = ('path', value.attribute.path, value.attribute.path, None)
        if attribute_key[0] == 'object' and synthetic_attribute_key in self._values:
            attribute_key = synthetic_attribute_key
        self._values.setdefault(attribute_key, []).append(value)

    def add(
        self,
        path: str,
        text: object,
        *,
        set_prefix: str = '',
        set_index: int | None = None,
        collection_index: int | None = None,
        dataset: bool = True,
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
            dataset=dataset,
        )

    def add_option(
        self,
        path: str,
        canonical_value: str | None,
        options: dict[str, str],
        *,
        text: str | None = None,
        set_prefix: str = '',
        set_index: int | None = None,
        collection_index: int | None = None,
        dataset: bool = True,
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
            dataset=dataset,
        )

    def add_unique_text(self, path: str, text: str) -> Value | None:
        normalized = normalize(text)
        if any(normalize(value.text) == normalized for value in self.get_values(path)):
            return None
        return self.add(path, text, collection_index=self.compute_next_collection_index(path), dataset=False)

    def get_values(self, path: str) -> list[Value]:
        lookup_position = 3 if is_uri(path) else 2
        if not any(attribute_key[lookup_position] == path for attribute_key in self._values):
            return []
        attribute = self.fetch_attribute(path)
        return list(self._values.get(self._attribute_key(attribute), ())) if attribute is not None else []

    def compute_next_set_index(self, anchor_path: str) -> int:
        attribute_values = self.get_values(anchor_path)
        return max((value.set_index for value in attribute_values), default=-1) + 1

    def compute_next_collection_index(self, path: str) -> int:
        attribute_values = self.get_values(path)
        return max((value.collection_index for value in attribute_values), default=-1) + 1

    def fetch_attribute(self, path: str) -> Attribute | None:
        if path in self._attributes:
            return self._attributes[path]
        if not path:
            self._attributes[path] = None
            return None
        attribute_uri = path if is_uri(path) else Attribute.build_uri(DEFAULT_URI_PREFIX, path)
        attribute = self.import_plugin.get_attribute(attribute_uri)
        # Preserve installed custom URI prefixes through the public import API.
        if attribute is None and not is_uri(path):
            matching_attributes_map = {}
            for attribute_uri in Attribute.objects.filter(path=path).values_list('uri', flat=True):
                matching_attribute = self.import_plugin.get_attribute(attribute_uri)
                if matching_attribute is not None:
                    matching_attributes_map[model_key(matching_attribute)] = matching_attribute
            if len(matching_attributes_map) == 1:
                attribute = next(iter(matching_attributes_map.values()))
            elif matching_attributes_map:
                self._ambiguous_attributes.add(path)
                self.warn(path, 'Ambiguous Attribute import destination')
        if attribute is not None and model_key(attribute)[0] == 'object':
            if sum(attribute_key[2] == attribute.path for attribute_key in self._values) > 1:
                self._ambiguous_attributes.add(path)
                self.warn(path, 'Ambiguous synthetic Attribute import destination')
                attribute = None
        self._attributes[path] = attribute
        return attribute

    def fetch_option(self, path: str) -> Option | None:
        if path in self._options:
            return self._options[path]
        if not path:
            self._options[path] = None
            return None
        option_uri = path if is_uri(path) else Option.build_uri(DEFAULT_URI_PREFIX, path)
        option = self.import_plugin.get_option(option_uri)
        if option is None and not is_uri(path):
            matching_options_map = {}
            for option_uri in Option.objects.filter(uri_path=path).values_list('uri', flat=True):
                matching_option = self.import_plugin.get_option(option_uri)
                if matching_option is not None:
                    matching_options_map[model_key(matching_option, matching_option.uri_path)] = matching_option
            if len(matching_options_map) == 1:
                option = next(iter(matching_options_map.values()))
            elif matching_options_map:
                self._ambiguous_options.add(path)
                self.warn(path, 'Ambiguous Option import destination')
        self._options[path] = option
        return option

    def _add_value(
        self,
        attribute: Attribute,
        text: object,
        *,
        option: Option | None = None,
        set_prefix: str = '',
        set_index: int | None = None,
        collection_index: int | None = None,
        dataset: bool = True,
    ) -> Value:
        value = Value(
            attribute=attribute,
            option=option,
            set_prefix=set_prefix,
            set_index=self.dataset_index if set_index is None and dataset else (set_index or 0),
            text=text,
        )
        if collection_index is not None:
            value.collection_index = collection_index
        self.import_plugin.values.append(value)
        self._append_value(value, resolved=True)
        return value

    def warn(self, field: str, reason: str, value: str | None = None) -> None:
        issue = MappingIssue(field, reason, value)
        if issue not in self.issues:
            self.issues.append(issue)
