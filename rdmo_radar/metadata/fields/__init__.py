"""Public building blocks for Python-defined RADAR application profiles."""

from .compound_writers import (
    AffiliationDestinations,
    FundingDestinations,
    IdentifierDestinations,
    PersonDestinations,
    write_funding,
    write_identifier,
    write_people,
)
from .contracts import (
    AttributeSelector,
    Coordinates,
    Destination,
    FieldMapping,
    FieldReader,
    FieldWriter,
    GroupSpec,
    ReadContext,
    Source,
    WriteContext,
)
from .dataset import read_data_sources, read_resource, read_rights, read_software, read_subjects
from .funding import FundingSources, read_funding
from .keywords import read_keywords
from .people import AffiliationSources, IdentifierSource, PersonSources, RoleSource, read_people
from .scalars import read_language, read_names, read_option, read_text, read_texts
from .writers import write_option, write_text, write_texts

__all__ = [
    'AffiliationDestinations',
    'AffiliationSources',
    'AttributeSelector',
    'Coordinates',
    'Destination',
    'FieldMapping',
    'FieldReader',
    'FieldWriter',
    'FundingDestinations',
    'FundingSources',
    'GroupSpec',
    'IdentifierDestinations',
    'IdentifierSource',
    'PersonDestinations',
    'PersonSources',
    'ReadContext',
    'RoleSource',
    'Source',
    'WriteContext',
    'read_data_sources',
    'read_funding',
    'read_keywords',
    'read_language',
    'read_names',
    'read_option',
    'read_people',
    'read_resource',
    'read_rights',
    'read_software',
    'read_subjects',
    'read_text',
    'read_texts',
    'write_funding',
    'write_identifier',
    'write_option',
    'write_people',
    'write_text',
    'write_texts',
]
