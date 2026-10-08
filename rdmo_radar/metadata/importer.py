from rdmo.projects.imports import Import as ProjectImport

from .dataset import write_dataset_fields
from .funding import merge_funding
from .people import merge_contributors, write_creators
from .rdmo import RDMOWriteContext
from .types import MappingIssue, RadarMetadata


def write_metadata(
    import_plugin: ProjectImport,
    metadata: RadarMetadata,
    set_index: int,
) -> list[MappingIssue]:
    context = RDMOWriteContext(import_plugin, set_index)
    write_dataset_fields(context, metadata)
    write_creators(context, metadata.creators)
    merge_contributors(context, metadata.contributors)
    merge_funding(context, metadata.funding_references)
    return context.issues
