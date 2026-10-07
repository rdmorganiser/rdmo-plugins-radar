from rdmo.projects.exports import Export

from .dataset import read_dataset_fields
from .funding import read_funding
from .people import read_contributors, read_creators
from .rdmo import RDMOReadContext
from .types import RadarMetadata


def compute_metadata(export: Export, set_index: int) -> RadarMetadata:
    context = RDMOReadContext(export, set_index=set_index)
    metadata = read_dataset_fields(context)
    metadata.creators = read_creators(context)
    metadata.contributors = read_contributors(context)
    metadata.funding_references = read_funding(context)
    metadata.mapping_issues = context.issues
    return metadata
