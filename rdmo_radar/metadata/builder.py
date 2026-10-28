"""Compose explicitly configured canonical field readers."""
from .fields.contracts import FieldMapping, ReadContext
from .types import MappingResult, RadarMetadata


def compute_metadata(context: ReadContext, *, fields: FieldMapping) -> MappingResult:
    metadata = RadarMetadata(**{
        target: reader(context, target=target) for target, reader in fields.readers.items()
    })
    provenance = tuple(context.provenance) if context.provenance is not None else None
    return MappingResult(metadata, tuple(context.issues), provenance)
