from collections.abc import Callable

from .dataset import read_dataset_fields
from .funding import read_funding
from .people import read_contributors, read_creators
from .read_context import ProjectReadContext
from .types import FundingReference, MappingResult, PersonOrOrganization, RadarMetadata


def compute_metadata(
    context: ProjectReadContext,
    *,
    dataset: Callable[[ProjectReadContext], RadarMetadata] = read_dataset_fields,
    creators: Callable[[ProjectReadContext], list[PersonOrOrganization]] = read_creators,
    contributors: Callable[[ProjectReadContext], list[PersonOrOrganization]] = read_contributors,
    funding: Callable[[ProjectReadContext], list[FundingReference]] = read_funding,
) -> MappingResult:
    metadata = dataset(context)
    metadata.creators = creators(context)
    metadata.contributors = contributors(context)
    metadata.funding_references = funding(context)
    return MappingResult(metadata, tuple(context.issues))
