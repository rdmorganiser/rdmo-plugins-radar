from collections.abc import Callable

from rdmo.projects.imports import Import as ProjectImport

from .dataset import write_dataset_fields
from .funding import merge_funding
from .people import merge_contributors, write_creators
from .types import FundingReference, MappingIssue, PersonOrOrganization, RadarMetadata
from .values import fetch_project_values
from .write_context import ProjectWriteContext


def write_metadata(
    import_plugin: ProjectImport,
    metadata: RadarMetadata,
    set_index: int,
    *,
    existing_values: dict | None = None,
    context: ProjectWriteContext | None = None,
    dataset: Callable[[ProjectWriteContext, RadarMetadata], None] = write_dataset_fields,
    creators: Callable[[ProjectWriteContext, list[PersonOrOrganization]], None] = write_creators,
    contributors: Callable[[ProjectWriteContext, list[PersonOrOrganization]], None] = merge_contributors,
    funding: Callable[[ProjectWriteContext, list[FundingReference]], None] = merge_funding,
) -> tuple[MappingIssue, ...]:
    if context is None:
        if existing_values is None:
            project = import_plugin.current_project
            existing_values = fetch_project_values(project) if project is not None else {}
        context = ProjectWriteContext(import_plugin, set_index, existing_values)
    elif context.import_plugin is not import_plugin or context.dataset_index != set_index:
        raise ValueError('Prepared import context does not match the import operation.')
    dataset(context, metadata)
    creators(context, metadata.creators)
    contributors(context, metadata.contributors)
    funding(context, metadata.funding_references)
    return tuple(context.issues)
