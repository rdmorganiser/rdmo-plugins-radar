from .types import (
    Affiliation,
    Agent,
    Description,
    FundingReference,
    GeoLocation,
    Identifier,
    MappingIssue,
    MappingResult,
    RadarMetadata,
    Resource,
    Rights,
    Software,
    SubjectArea,
)

__all__ = (
    'Affiliation',
    'Agent',
    'AttributeRef',
    'Description',
    'FundingReference',
    'GeoLocation',
    'Identifier',
    'MappingIssue',
    'MappingResult',
    'RDMOReadContext',
    'RDMOWriteContext',
    'RadarMetadata',
    'Resource',
    'Rights',
    'Software',
    'SubjectArea',
)


def __getattr__(name):
    # Canonical metadata and services must be importable without initializing Django.
    if name in ('AttributeRef', 'RDMOReadContext', 'RDMOWriteContext'):
        from . import rdmo
        return getattr(rdmo, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
