from dataclasses import dataclass, field

from django.utils.html import strip_tags

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.imports import Import as ProjectImport
from rdmo.projects.models import Value

from .types import MappingIssue
from .values import get_scoped_values

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


@dataclass
class RDMOReadContext:
    """Mapping scopes and diagnostics over prepared data; never loads or caches RDMO models."""
    values: dict[str, list[Value]]
    placements: dict[str, tuple]
    set_prefix: str = ''
    set_index: int = 0
    scope: str = 'dataset'
    issues: list[MappingIssue] = field(default_factory=list)

    def shared(self):
        return RDMOReadContext(self.values, self.placements, scope='project', issues=self.issues)

    def group(self, prefix, index):
        return RDMOReadContext(self.values, self.placements, prefix, index, scope='group', issues=self.issues)

    def groups(self, *paths):
        positions = {(value.set_prefix, value.set_index) for path in paths for value in self.get_values(path)}
        return [self.group(prefix, index) for prefix, index in sorted(positions)]

    def warn(self, target, source, reason, value=None):
        issue = MappingIssue(SCALAR_TARGETS.get(target, target), reason, value, source)
        if issue not in self.issues:
            self.issues.append(issue)

    def get_text(self, path: str) -> str | None:
        texts = self.get_texts(path)
        if len(texts) > 1:
            self.warn(path, path, 'Multiple answers for a scalar field', '; '.join(texts))
            return None
        return texts[0] if texts else None

    def get_values(self, path: str) -> list[Value]:
        return get_scoped_values(
            self.values, self.placements, path, int(self.set_index) if self.scope == 'dataset' else None,
            (self.set_prefix, self.set_index) if self.scope == 'group' else None,
        )

    def get_texts(self, path: str) -> list[str]:
        return list(dict.fromkeys(value.text.strip() for value in self.get_values(path)
                                  if value.text and value.text.strip() and not value.option))

    def get_option(
        self,
        path: str,
        options: dict[str, str],
        default: str | None = None,
    ) -> str | None:
        values = [value for value in self.get_values(path) if value.is_true]
        mapped = list(dict.fromkeys(options.get(value.option.uri_path) if value.option else None
                                    for value in values))
        if values and (None in mapped or len(mapped) > 1):
            self.warn(path, path, 'Unmapped or conflicting controlled answers')
            return default
        return mapped[0] if mapped else default

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
    existing_values: dict[str, list[Value]]
    issues: list[MappingIssue] = field(default_factory=list)
    _values: dict[str, list[Value]] = field(init=False, repr=False)
    _attributes: dict[str, Attribute | None] = field(default_factory=dict, init=False, repr=False)
    _options: dict[str, Option | None] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        # Copy the buckets: staging must not change the prepared project read.
        self._values = {path: list(values) for path, values in self.existing_values.items()}
        for value in self.import_plugin.values:
            if value.attribute is not None:
                self._values.setdefault(value.attribute.path, []).append(value)

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
            self.warn(path, 'RDMO Attribute is not installed', canonical_value)
            return None
        if option is None:
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
        return list(self._values.get(path, ()))

    def compute_next_set_index(self, anchor_path: str) -> int:
        values = self.get_values(anchor_path)
        return max((value.set_index for value in values), default=-1) + 1

    def compute_next_collection_index(self, path: str) -> int:
        values = self.get_values(path)
        return max((value.collection_index for value in values), default=-1) + 1

    def fetch_attribute(self, path: str) -> Attribute | None:
        if path in self._attributes:
            return self._attributes[path]
        attribute = self.import_plugin.get_attribute(TERMS_PREFIX + path)
        # Preserve installed custom URI prefixes through the public import API.
        if attribute is None:
            for uri in Attribute.objects.filter(path=path).values_list('uri', flat=True):
                attribute = self.import_plugin.get_attribute(uri)
                if attribute is not None:
                    break
        self._attributes[path] = attribute
        return attribute

    def fetch_option(self, path: str) -> Option | None:
        if path in self._options:
            return self._options[path]
        option = None
        for prefix in OPTION_PREFIXES:
            option = self.import_plugin.get_option(prefix + path)
            if option is not None:
                break
        if option is None:
            for uri in Option.objects.filter(uri_path=path).values_list('uri', flat=True):
                option = self.import_plugin.get_option(uri)
                if option is not None:
                    break
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
        self._values.setdefault(attribute.path, []).append(value)
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
