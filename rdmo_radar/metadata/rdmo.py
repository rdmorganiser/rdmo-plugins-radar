from dataclasses import dataclass, field

from django.utils.html import strip_tags

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.imports import Import as ProjectImport
from rdmo.projects.models import Value

from .template_framework import ATTRIBUTE_TO_RADAR_FIELDS, DEFAULT_URI_PREFIX, get_dataset_values
from .types import MappingIssue
from .values import (
    get_scoped_values,
    is_uri,
    model_key,
    prepare_read_data,
    prepare_values,
    selector_key,
    selector_label,
)


@dataclass
class RDMOReadContext:
    """Scoped access and diagnostics over prepared RDMO Values.

    Attribute arguments named ``path`` also accept full URIs, IDs, and models.
    The existing argument and field names remain compatible with custom mappings.
    """

    values: dict
    placements: dict
    set_prefix: str = ''
    set_index: int = 0
    scope: str = 'dataset'
    issues: list[MappingIssue] = field(default_factory=list)
    prepared: tuple | None = field(default=None, repr=False)
    dataset_prefix: str | None = None
    project: object | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.prepared is None:
            self.prepared = prepare_read_data(self.values, self.placements)

    def shared(self):
        return RDMOReadContext(
            self.values,
            self.placements,
            scope='project',
            issues=self.issues,
            prepared=self.prepared,
            project=self.project,
        )

    def group(self, prefix, index):
        return RDMOReadContext(
            self.values,
            self.placements,
            prefix,
            index,
            scope='group',
            issues=self.issues,
            prepared=self.prepared,
            project=self.project,
        )

    def resolve_attribute(self, selector):
        """Resolve only prepared project/catalog identities; never query installed models."""
        _, _, attribute_lookup_map = self.prepared
        attribute_keys = attribute_lookup_map.get(selector_key(selector), ())
        if len(attribute_keys) > 1:
            attribute_label = selector_label(selector)
            self.warn(
                attribute_label,
                attribute_label,
                'Ambiguous RDMO Attribute',
                '; '.join(sorted(attribute_key[3] or str(attribute_key[1]) for attribute_key in attribute_keys)),
            )
            return None
        return attribute_keys[0] if attribute_keys else None

    def groups(self, *paths):
        set_positions = {
            (value.set_prefix, value.set_index)
            for attribute_reference in paths
            for value in self.get_values(attribute_reference)
        }
        return [self.group(set_prefix, set_index) for set_prefix, set_index in sorted(set_positions)]

    def warn(self, target, source, reason, value=None):
        target = selector_label(target)
        source = selector_label(source)
        issue = MappingIssue(ATTRIBUTE_TO_RADAR_FIELDS.get(target, target), reason, value, source)
        if issue not in self.issues:
            self.issues.append(issue)

    def get_text(self, path: str | int | Attribute) -> str | None:
        texts = self.get_texts(path)
        if len(texts) > 1:
            self.warn(path, path, 'Multiple answers for a scalar field', '; '.join(texts))
            return None
        return texts[0] if texts else None

    def get_values(self, path: str | int | Attribute) -> list[Value]:
        attribute_key = self.resolve_attribute(path)
        if attribute_key is None:
            return []
        if self.scope == 'dataset':
            return get_dataset_values(self, attribute_key)
        attribute_values_map, attribute_placements_map, _ = self.prepared
        return get_scoped_values(
            attribute_values_map,
            attribute_placements_map,
            attribute_key,
            group=(self.set_prefix, self.set_index) if self.scope == 'group' else None,
        )

    def get_values_by_uri(self, uri: str) -> list[Value]:
        if not is_uri(uri):
            raise ValueError('Expected a full Attribute URI.')
        return self.get_values(uri)

    def get_values_by_attribute_id(self, attribute_id: int) -> list[Value]:
        return self.get_values(attribute_id)

    def get_texts(self, path: str | int | Attribute) -> list[str]:
        return list(
            dict.fromkeys(
                value.text.strip()
                for value in self.get_values(path)
                if value.text and value.text.strip() and not value.option
            )
        )

    def get_option(
        self,
        path: str | int | Attribute,
        options: dict[str, str],
        default: str | None = None,
    ) -> str | None:
        option_values = [value for value in self.get_values(path) if value.is_true]
        mapped_options = list(dict.fromkeys(self.map_options(path, options, values=option_values)))
        if option_values and (None in mapped_options or len(mapped_options) > 1):
            self.warn(path, path, 'Unmapped or conflicting controlled answers')
            return default
        return mapped_options[0] if mapped_options else default

    def map_options(self, path, options, *, values=None):
        """Map each Option by full URI, or an unambiguous legacy vocabulary path."""
        if values is None:
            values = self.get_values(path)
        option_identity_map = {}
        for value in values:
            if value.option is not None:
                option = value.option
                option_key = model_key(option, option.uri_path)
                option_identity_map.setdefault(option.uri_path, set()).add(option_key)
        mapped_options = []
        for value in values:
            option = value.option
            if option is None:
                mapped_options.append(None)
            elif option.uri and option.uri in options:
                mapped_options.append(options[option.uri])
            elif option.uri_path in options and len(option_identity_map[option.uri_path]) > 1:
                self.warn(path, path, 'Ambiguous RDMO Option path', option.uri_path)
                mapped_options.append(None)
            else:
                mapped_options.append(options.get(option.uri_path))
        return mapped_options

    def get_identifier(self, path):
        identifiers = list(
            dict.fromkeys(
                value.external_id or value.text for value in self.get_values(path) if value.external_id or value.text
            )
        )
        if len(identifiers) == 1 and '<' not in identifiers[0]:
            return identifiers[0]
        if identifiers:
            self.warn('nameIdentifier', path, 'Identifier is ambiguous or contains display markup')
        return None


@dataclass
class RDMOWriteContext:
    """Merge prepared answers and stage unsaved Values for one import mapping operation."""

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
            attribute_candidates_map = {}
            for attribute_uri in Attribute.objects.filter(path=path).values_list('uri', flat=True):
                candidate_attribute = self.import_plugin.get_attribute(attribute_uri)
                if candidate_attribute is not None:
                    attribute_candidates_map[model_key(candidate_attribute)] = candidate_attribute
            if len(attribute_candidates_map) == 1:
                attribute = next(iter(attribute_candidates_map.values()))
            elif attribute_candidates_map:
                self._ambiguous_attributes.add(path)
                self.warn(path, 'Ambiguous RDMO Attribute import destination')
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
            option_candidates_map = {}
            for option_uri in Option.objects.filter(uri_path=path).values_list('uri', flat=True):
                candidate_option = self.import_plugin.get_option(option_uri)
                if candidate_option is not None:
                    option_candidates_map[model_key(candidate_option, candidate_option.uri_path)] = candidate_option
            if len(option_candidates_map) == 1:
                option = next(iter(option_candidates_map.values()))
            elif option_candidates_map:
                self._ambiguous_options.add(path)
                self.warn(path, 'Ambiguous RDMO Option import destination')
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


def get_option_path(options: dict[str, str], canonical_value: str) -> str | None:
    return next((option_reference for option_reference, value in options.items() if value == canonical_value), None)


def normalize(value: object) -> str:
    return ' '.join(str(value).split()).casefold()


def answer_label(value: Value) -> str:
    """Read option labels without Value.value's rendered display HTML."""
    label = strip_tags(str(value.option.text)) if value.option else ''
    text = value.text.strip() if value.text else ''
    return f'{label}: {text}' if label and text and label != text else text or label
