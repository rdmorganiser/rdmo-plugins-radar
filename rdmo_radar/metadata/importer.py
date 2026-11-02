"""Compose explicit import strategies; destination allocation belongs to profiles."""
from dataclasses import fields as dataclass_fields

from .fields.contracts import FieldMapping, WriteContext
from .types import MappingIssue, RadarMetadata


def write_metadata(context: WriteContext, metadata: RadarMetadata, *, fields: FieldMapping) -> tuple[MappingIssue, ...]:
    for target, writer in fields.writers.items():
        writer(context, getattr(metadata, target), target=target)
    for item in dataclass_fields(metadata):
        if item.name not in fields.writers and getattr(metadata, item.name):
            context.warn(item.name, 'No configured RDMO import destination')
    return tuple(context.issues)
