from collections.abc import Callable

from .dataset import read_dataset_fields
from .funding import read_funding
from .people import read_contributors, read_creators
from .rdmo import RDMOReadContext
from .types import FundingReference, MappingResult, PersonOrOrganization, RadarMetadata


def compute_metadata(
    context: RDMOReadContext,
    *,
    dataset: Callable[[RDMOReadContext], RadarMetadata] = read_dataset_fields,
    creators: Callable[[RDMOReadContext], list[PersonOrOrganization]] = read_creators,
    contributors: Callable[[RDMOReadContext], list[PersonOrOrganization]] = read_contributors,
    funding: Callable[[RDMOReadContext], list[FundingReference]] = read_funding,
) -> MappingResult:
    metadata = dataset(context)
    metadata.creators = creators(context)
    metadata.contributors = contributors(context)
    metadata.funding_references = funding(context)
    return MappingResult(metadata, tuple(context.issues))
