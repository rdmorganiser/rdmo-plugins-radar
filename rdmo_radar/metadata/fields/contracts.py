"""Explicit field strategies and small, immutable mapping parameters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol

from ..types import MappingAttempt, MappingIssue, RadarMetadata

if TYPE_CHECKING:
    from rdmo.domain.models import Attribute
    from rdmo.projects.models import Value

type AttributeSelector = str | int | Attribute


class ReadContext(Protocol):
    issues: list[MappingIssue]
    provenance: list[MappingAttempt] | None

    def get_values(self, path: AttributeSelector) -> list[Value]: ...
    def get_text(self, path: AttributeSelector, *, target=None) -> str | None: ...
    def get_texts(self, path: AttributeSelector, *, target=None) -> list[str]: ...
    def get_option(self, path: AttributeSelector, options, *, target=None): ...
    def get_identifier(self, path: AttributeSelector, *, target=None) -> str | None: ...
    def get_scope_values(self) -> list[Value]: ...
    def map_options(self, path, options, *, values=None): ...
    def shared(self) -> ReadContext: ...
    def group(self, prefix, index) -> ReadContext: ...
    def groups(self, *paths) -> list[ReadContext]: ...
    def descendants(self, group, anchors) -> ReadContext: ...
    def has_shared_placement(self, path, anchors) -> bool: ...
    def warn(self, target, source, reason, value=None) -> None: ...
    def record_mapping(self, target, *, sources=(), value=None, outcome='mapped', reason='') -> None: ...
    def record_empty_mapping(self, target, path) -> None: ...


class WriteContext(Protocol):
    issues: list[MappingIssue]

    def add(self, path, text, **kwargs): ...
    def add_option(self, path, canonical_value, options, **kwargs): ...
    def get_values(self, path): ...
    def warn(self, field, reason, value=None) -> None: ...


class FieldReader[T](Protocol):
    def __call__(self, context: ReadContext, *, target: str) -> T: ...


class FieldWriter[T](Protocol):
    def __call__(self, context: WriteContext, value: T, *, target: str) -> None: ...


@dataclass(frozen=True)
class Source:
    attribute: AttributeSelector
    scope: Literal['current', 'project'] = 'current'

    def __post_init__(self):
        if self.scope not in ('current', 'project'):
            raise ValueError(f'Unknown source scope: {self.scope}')

    def context(self, context):
        return context.shared() if self.scope == 'project' else context


@dataclass(frozen=True)
class GroupSpec:
    anchors: tuple[AttributeSelector, ...]
    scope: Literal['current', 'project'] = 'current'

    def context(self, context):
        return Source(self.anchors[0], self.scope).context(context)

    def __post_init__(self):
        object.__setattr__(self, 'anchors', tuple(self.anchors))
        if not self.anchors or self.scope not in ('current', 'project'):
            raise ValueError('A group needs anchors and an explicit valid scope.')


@dataclass(frozen=True)
class Coordinates:
    set_prefix: str = ''
    set_index: int = 0
    collection_index: int = 0

    def kwargs(self):
        return {'set_prefix': self.set_prefix, 'set_index': self.set_index, 'collection_index': self.collection_index}


@dataclass(frozen=True)
class Destination:
    attribute: AttributeSelector
    coordinates: Coordinates


@dataclass(frozen=True)
class FieldMapping:
    readers: Mapping[str, FieldReader] = field(default_factory=dict)
    writers: Mapping[str, FieldWriter] = field(default_factory=dict)

    def __post_init__(self):
        known = {item.name for item in fields(RadarMetadata)}
        for name in ('readers', 'writers'):
            callbacks = dict(getattr(self, name))
            if unknown := set(callbacks) - known:
                raise ValueError(f'Unknown canonical metadata fields: {sorted(unknown)}')
            if any(not callable(callback) for callback in callbacks.values()):
                raise TypeError('Field mappings require callable strategies.')
            object.__setattr__(self, name, MappingProxyType(callbacks))
