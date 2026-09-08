from dataclasses import dataclass, field

from rdmo.projects.exports import Export
from rdmo.projects.imports import Import as ProjectImport
from rdmo.projects.models import Value

from .types import MappingIssue

TERMS_PREFIX = 'https://rdmorganiser.github.io/terms/domain/'
OPTION_PREFIXES = (
    'https://rdmorganiser.github.io/terms/options/',
    'https://rdmo.jochenklar.dev/terms/options/',
)


@dataclass(frozen=True)
class AttributeRef:
    path: str
    aliases: tuple[str, ...] = ()

    @property
    def uri(self) -> str:
        return TERMS_PREFIX + self.path

    @property
    def paths(self) -> tuple[str, ...]:
        return (self.path, *self.aliases)


@dataclass
class RDMOReadContext:
    export: Export
    set_prefix: str = ''
    set_index: int = 0

    def get_text(self, attribute: AttributeRef | str, collection_index: int = 0) -> str | None:
        for path in self._paths(attribute):
            value = self.export.get_text(
                path,
                set_prefix=self.set_prefix,
                set_index=self.set_index,
                collection_index=collection_index,
            )
            if value not in (None, ''):
                return value
        return None

    def get_values(self, attribute: AttributeRef | str) -> list[Value]:
        for path in self._paths(attribute):
            values = list(self.export.get_values(path, set_prefix=self.set_prefix, set_index=self.set_index))
            if values:
                return values
        return []

    def get_texts(self, attribute: AttributeRef | str) -> list[str]:
        for path in self._paths(attribute):
            values = self.export.get_list(path, set_prefix=self.set_prefix, set_index=self.set_index)
            if values:
                return values
        return []

    def get_option(
        self,
        attribute: AttributeRef | str,
        options: dict[str, str],
        collection_index: int = 0,
        default: str | None = None,
    ) -> str | None:
        for path in self._paths(attribute):
            value = self.export.get_option(
                options,
                path,
                set_prefix=self.set_prefix,
                set_index=self.set_index,
                collection_index=collection_index,
            )
            if value:
                return value
        return default

    @staticmethod
    def _paths(attribute: AttributeRef | str) -> tuple[str, ...]:
        return attribute.paths if isinstance(attribute, AttributeRef) else (attribute,)


@dataclass
class RDMOWriteContext:
    import_plugin: ProjectImport
    dataset_index: int
    issues: list[MappingIssue] = field(default_factory=list)

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
        attribute = self.get_attribute(path)
        if attribute is None:
            self.warn(path, 'RDMO Attribute is not installed', str(text))
            return None
        value = Value(
            attribute=attribute,
            set_prefix=set_prefix,
            set_index=self.dataset_index if set_index is None and dataset else (set_index or 0),
            text=text,
        )
        if collection_index is not None:
            value.collection_index = collection_index
        self.import_plugin.values.append(value)
        return value

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
        attribute = self.get_attribute(path)
        option = self.get_option(option_path)
        if attribute is None:
            self.warn(path, 'RDMO Attribute is not installed', canonical_value)
            return None
        if option is None:
            self.warn(path, f'RDMO Option is not installed: {option_path}', canonical_value)
            return None
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
        return value

    def add_unique_text(self, path: str, text: str) -> Value | None:
        normalized = normalize(text)
        if any(normalize(value.text) == normalized for value in self.values_for(path)):
            return None
        return self.add(path, text, collection_index=self.next_collection_index(path), dataset=False)

    def values_for(self, path: str) -> list[Value]:
        existing = []
        project = getattr(self.import_plugin, 'current_project', None)
        if project is not None:
            existing = list(project.values.filter(snapshot=None, attribute__path=path))
        staged = [
            value for value in self.import_plugin.values
            if value.attribute is not None and value.attribute.path == path
        ]
        return [*existing, *staged]

    def next_set_index(self, anchor_path: str) -> int:
        values = self.values_for(anchor_path)
        return max((value.set_index for value in values), default=-1) + 1

    def next_collection_index(self, path: str) -> int:
        values = self.values_for(path)
        return max((value.collection_index for value in values), default=-1) + 1

    def get_attribute(self, path: str):
        for attribute in getattr(self.import_plugin, '_attributes', {}).values():
            if attribute.path == path:
                return attribute
        return self.import_plugin.get_attribute(TERMS_PREFIX + path)

    def get_option(self, path: str):
        for option in getattr(self.import_plugin, '_options', {}).values():
            if option.uri_path == path:
                return option
        for prefix in OPTION_PREFIXES:
            option = self.import_plugin.get_option(prefix + path)
            if option is not None:
                return option
        return None

    def warn(self, field: str, reason: str, value: str | None = None) -> None:
        issue = MappingIssue(field, reason, value)
        if issue not in self.issues:
            self.issues.append(issue)


def get_option_path(options: dict[str, str], canonical_value: str) -> str | None:
    return next((path for path, value in options.items() if value == canonical_value), None)


def normalize(value: object) -> str:
    return ' '.join(str(value).split()).casefold()
