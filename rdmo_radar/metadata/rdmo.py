from dataclasses import dataclass, field

from django.utils.html import strip_tags

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.imports import Import as ProjectImport
from rdmo.projects.models import Value

from .template_framework import OPTION_PREFIXES, SCALAR_TARGETS, TERMS_PREFIX, get_dataset_values
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
    """Mapping scopes and diagnostics over prepared data; never loads or caches RDMO models."""
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
        return RDMOReadContext(self.values, self.placements, scope='project', issues=self.issues,
                               prepared=self.prepared, project=self.project)

    def group(self, prefix, index):
        return RDMOReadContext(self.values, self.placements, prefix, index, scope='group', issues=self.issues,
                               prepared=self.prepared, project=self.project)

    def resolve_attribute(self, selector):
        """Resolve only prepared project/catalog identities; never query installed models."""
        keys = self.prepared[2].get(selector_key(selector), ())
        if len(keys) > 1:
            source = selector_label(selector)
            self.warn(source, source, 'Ambiguous RDMO Attribute',
                      '; '.join(sorted(key[3] or str(key[1]) for key in keys)))
            return None
        return keys[0] if keys else None

    def groups(self, *paths):
        positions = {(value.set_prefix, value.set_index) for path in paths for value in self.get_values(path)}
        return [self.group(prefix, index) for prefix, index in sorted(positions)]

    def warn(self, target, source, reason, value=None):
        target = selector_label(target)
        source = selector_label(source)
        issue = MappingIssue(SCALAR_TARGETS.get(target, target), reason, value, source)
        if issue not in self.issues:
            self.issues.append(issue)

    def get_text(self, path: str | int | Attribute) -> str | None:
        texts = self.get_texts(path)
        if len(texts) > 1:
            self.warn(path, path, 'Multiple answers for a scalar field', '; '.join(texts))
            return None
        return texts[0] if texts else None

    def get_values(self, path: str | int | Attribute) -> list[Value]:
        key = self.resolve_attribute(path)
        if key is None:
            return []
        if self.scope == 'dataset':
            return get_dataset_values(self, key)
        values, placements, _ = self.prepared
        return get_scoped_values(
            values, placements, key,
            group=(self.set_prefix, self.set_index) if self.scope == 'group' else None,
        )

    def get_values_by_uri(self, uri: str) -> list[Value]:
        if not is_uri(uri):
            raise ValueError('Expected a full Attribute URI.')
        return self.get_values(uri)

    def get_values_by_attribute_id(self, attribute_id: int) -> list[Value]:
        return self.get_values(attribute_id)

    def get_texts(self, path: str | int | Attribute) -> list[str]:
        return list(dict.fromkeys(value.text.strip() for value in self.get_values(path)
                                  if value.text and value.text.strip() and not value.option))

    def get_option(
        self,
        path: str | int | Attribute,
        options: dict[str, str],
        default: str | None = None,
    ) -> str | None:
        values = [value for value in self.get_values(path) if value.is_true]
        mapped = list(dict.fromkeys(self.map_options(path, options, values=values)))
        if values and (None in mapped or len(mapped) > 1):
            self.warn(path, path, 'Unmapped or conflicting controlled answers')
            return default
        return mapped[0] if mapped else default

    def map_options(self, path, options, *, values=None):
        """Map each Option by full URI, or an unambiguous legacy vocabulary path."""
        if values is None:
            values = self.get_values(path)
        option_keys = {}
        for value in values:
            if value.option is not None:
                option = value.option
                key = model_key(option, option.uri_path)
                option_keys.setdefault(option.uri_path, set()).add(key)
        mapped = []
        for value in values:
            option = value.option
            if option is None:
                mapped.append(None)
            elif option.uri and option.uri in options:
                mapped.append(options[option.uri])
            elif option.uri_path in options and len(option_keys[option.uri_path]) > 1:
                self.warn(path, path, 'Ambiguous RDMO Option path', option.uri_path)
                mapped.append(None)
            else:
                mapped.append(options.get(option.uri_path))
        return mapped

    def get_identifier(self, path):
        identifiers = list(dict.fromkeys(value.external_id or value.text for value in self.get_values(path)
                                         if value.external_id or value.text))
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
        key = model_key(attribute)
        for current in self._values:
            if current[:2] == key[:2]:
                return current
        if key[0] == 'object':
            # A synthetic import API destination can alias one prepared fixture bucket.
            matches = [key for key in self._values if key[2] == attribute.path]
            if len(matches) == 1:
                return matches[0]
        return key

    def _append_value(self, value, *, resolved=False):
        key = self._attribute_key(value.attribute) if resolved else model_key(value.attribute)
        if not resolved:
            key = next((current for current in self._values if current[:2] == key[:2]), key)
        synthetic = ('path', value.attribute.path, value.attribute.path, None)
        if key[0] == 'object' and synthetic in self._values:
            key = synthetic
        self._values.setdefault(key, []).append(value)

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
            attribute, text, set_prefix=set_prefix, set_index=set_index,
            collection_index=collection_index, dataset=dataset,
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
        option_path = get_option_path(options, canonical_value)
        if option_path is None:
            self.warn(path, 'RADAR controlled value has no RDMO mapping', canonical_value)
            return None
        attribute = self.fetch_attribute(path)
        option = self.fetch_option(option_path)
        if attribute is None:
            if path not in self._ambiguous_attributes:
                self.warn(path, 'RDMO Attribute is not installed', canonical_value)
            return None
        if option is None:
            if option_path not in self._ambiguous_options:
                self.warn(path, f'RDMO Option is not installed: {option_path}', canonical_value)
            return None
        return self._add_value(
            attribute, text, option=option, set_prefix=set_prefix, set_index=set_index,
            collection_index=collection_index, dataset=dataset,
        )

    def add_unique_text(self, path: str, text: str) -> Value | None:
        normalized = normalize(text)
        if any(normalize(value.text) == normalized for value in self.get_values(path)):
            return None
        return self.add(path, text, collection_index=self.compute_next_collection_index(path), dataset=False)

    def get_values(self, path: str) -> list[Value]:
        position = 3 if is_uri(path) else 2
        if not any(key[position] == path for key in self._values):
            return []
        attribute = self.fetch_attribute(path)
        return list(self._values.get(self._attribute_key(attribute), ())) if attribute is not None else []

    def compute_next_set_index(self, anchor_path: str) -> int:
        values = self.get_values(anchor_path)
        return max((value.set_index for value in values), default=-1) + 1

    def compute_next_collection_index(self, path: str) -> int:
        values = self.get_values(path)
        return max((value.collection_index for value in values), default=-1) + 1

    def fetch_attribute(self, path: str) -> Attribute | None:
        if path in self._attributes:
            return self._attributes[path]
        attribute = self.import_plugin.get_attribute(path if is_uri(path) else TERMS_PREFIX + path)
        # Preserve installed custom URI prefixes through the public import API.
        if attribute is None and not is_uri(path):
            candidates = {}
            for uri in Attribute.objects.filter(path=path).values_list('uri', flat=True):
                candidate = self.import_plugin.get_attribute(uri)
                if candidate is not None:
                    candidates[model_key(candidate)] = candidate
            if len(candidates) == 1:
                attribute = next(iter(candidates.values()))
            elif candidates:
                self._ambiguous_attributes.add(path)
                self.warn(path, 'Ambiguous RDMO Attribute import destination')
        if attribute is not None and model_key(attribute)[0] == 'object':
            if sum(key[2] == attribute.path for key in self._values) > 1:
                self._ambiguous_attributes.add(path)
                self.warn(path, 'Ambiguous synthetic Attribute import destination')
                attribute = None
        self._attributes[path] = attribute
        return attribute

    def fetch_option(self, path: str) -> Option | None:
        if path in self._options:
            return self._options[path]
        option = None
        for uri in (path,) if is_uri(path) else tuple(prefix + path for prefix in OPTION_PREFIXES):
            option = self.import_plugin.get_option(uri)
            if option is not None:
                break
        if option is None and not is_uri(path):
            candidates = {}
            for uri in Option.objects.filter(uri_path=path).values_list('uri', flat=True):
                candidate = self.import_plugin.get_option(uri)
                if candidate is not None:
                    candidates[model_key(candidate, candidate.uri_path)] = candidate
            if len(candidates) == 1:
                option = next(iter(candidates.values()))
            elif candidates:
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
    return next((path for path, value in options.items() if value == canonical_value), None)


def normalize(value: object) -> str:
    return ' '.join(str(value).split()).casefold()


def answer_label(value: Value) -> str:
    """Read option labels without Value.value's rendered display HTML."""
    label = strip_tags(str(value.option.text)) if value.option else ''
    text = value.text.strip() if value.text else ''
    return f'{label}: {text}' if label and text and label != text else text or label
