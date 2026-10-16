"""Completeness checks on canonical metadata, independent of output format."""

from .types import RadarMetadata


def missing_required_fields(metadata: RadarMetadata) -> tuple[str, ...]:
    """Return missing publication fields; incomplete drafts remain exportable."""
    checks = {
        'identifier': metadata.identifier.value if metadata.identifier else None,
        'identifier.identifierType': metadata.identifier.identifier_type if metadata.identifier else None,
        'creators.creator': any(value.name for value in metadata.creators),
        'title': metadata.title,
        'publishers.publisher': any(value.name for value in metadata.publishers),
        'productionYear': metadata.production_year,
        'subjectAreas.subjectArea': any(value.controlled_name for value in metadata.subject_areas),
        'resource.value': metadata.resource.value if metadata.resource else None,
        'resource.resourceType': metadata.resource.resource_type if metadata.resource else None,
        'rights.controlledRights': metadata.rights.controlled if metadata.rights else None,
        'rightsHolders.rightsHolder': any(value.name for value in metadata.rights_holders),
    }
    return tuple(path for path, value in checks.items() if not value)
