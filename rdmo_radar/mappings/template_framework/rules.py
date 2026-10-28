"""Established Template Framework scope and allocation rules; no mapping profiles."""

from ...metadata.values import coordinates, get_scoped_values, matches_placement, prepare_read_data, select_values

# Attributes used to discover dataset records and constrain their collection scope.
DATASET_ATTRIBUTES = ('project/dataset/id', 'project/dataset/title')

DEFAULT_URI_PREFIX = 'https://rdmorganiser.github.io/terms/'

# Attribute paths to RADAR field names in diagnostics; this does not validate scalar values.
ATTRIBUTE_TO_RADAR_FIELDS = {
    'project/dataset/title': 'title',
    'project/dataset/id': 'title',
    'project/dataset/description': 'resource',
    'project/dataset/pids/system': 'identifier.identifierType',
    'project/dataset/data_publication_pid': 'identifier',
    'project/dataset/language': 'language',
    'project/dataset/usage_technology/geo_location': 'geoLocations',
    'project/acronym': 'additionalTitles',
    'project/funder/name': 'fundingReferences.funderName',
    'project/funder/grant_nr': 'fundingReferences.awardNumber',
    'project/funder/programme/title': 'fundingReferences.awardTitle',
    'project/funder/programme/url': 'fundingReferences.awardURI',
    'project/funder/id/type': 'fundingReferences.funderIdentifier.type',
    'project/dataset/owner/name': 'creators.creatorName',
    'project/dataset/owner/given_name': 'creators.givenName',
    'project/dataset/owner/family_name': 'creators.familyName',
    'project/dataset/owner/orcid': 'creators.nameIdentifier',
    'project/dataset/owner/ror': 'creators.nameIdentifier',
    'project/dataset/owner/organization/name': 'creators.creatorAffiliation',
    'project/dataset/owner/organization/name/identifier/value': 'creators.creatorAffiliation.affiliationIdentifier',
    'project/dataset/owner/organization/name/identifier/type': (
        'creators.creatorAffiliation.affiliationIdentifierScheme'
    ),
    'project/dataset/curation/responsible_person/name': 'publishers',
    'project/dataset/ipr/rightsholder': 'rightsHolders',
    'project/research_question/keywords': 'keywords',
    'project/research_question/keywords/gnd': 'keywords',
    'project/contributor/name': 'contributors.contributorName',
    'project/contributor/person_or_entity': 'contributors.nameType',
    'project/contributor/given_name': 'contributors.givenName',
    'project/contributor/family_name': 'contributors.familyName',
    'project/contributor/orcid': 'contributors.nameIdentifier',
    'project/contributor/role': 'contributors.contributorType',
    'dmp/contributor/role': 'contributors.contributorType',
}


def select_template_framework_values(context, key):
    """Constrain dataset answers, retaining generic project and group selection."""
    if context.scope != 'dataset':
        return select_values(context, key)
    attribute_values_map, attribute_placements_map, attribute_lookup_map = context.prepared
    constraints = {
        anchor: context.set_index
        for attribute_path in DATASET_ATTRIBUTES
        for anchor in attribute_lookup_map.get(('path', attribute_path), ())
    }
    if attribute_placements_map.get(key):
        attribute_values = get_scoped_values(
            attribute_values_map, attribute_placements_map, key, constraints=constraints
        )
        if context.dataset_prefix is None:
            return attribute_values
        dataset_coordinates = tuple(context.dataset_prefix.split('|')) if context.dataset_prefix else ()
        return [
            value
            for value in attribute_values
            if any(
                matches_placement(value, placement, constraints)
                and all(
                    coordinates(value)[:level] == dataset_coordinates
                    for level, (anchor, _) in enumerate(placement)
                    if anchor in constraints
                )
                for placement in attribute_placements_map[key]
            )
        ]
    attribute_values = attribute_values_map.get(key, ())
    if key[2].startswith(('project/dataset/creator/', 'project/dataset/owner/')):
        set_prefix = (
            f'{context.dataset_prefix}|{context.set_index}' if context.dataset_prefix else str(context.set_index)
        )
        return [
            value
            for value in attribute_values
            if value.set_prefix and coordinates(value)[: len(set_prefix.split('|'))] == tuple(set_prefix.split('|'))
        ]
    return [
        value
        for value in attribute_values
        if value.set_prefix == (context.dataset_prefix or '') and value.set_index == context.set_index
    ]


def compute_next_dataset_index(values, import_plugin=None, *, context=None):
    """Allocate after current titles, scoped to the resolved import destination."""
    if context is not None:
        attribute_values = context.get_values('project/dataset/title')
    elif import_plugin is not None:
        from ...metadata.fields.contracts import Coordinates
        from ...metadata.write_context import ProjectWriteContext

        attribute_values = ProjectWriteContext(
            import_plugin, values, Coordinates(), namespace=DEFAULT_URI_PREFIX
        ).get_values('project/dataset/title')
    else:
        attribute_values_map, _, attribute_lookup_map = prepare_read_data(values, {})
        attribute_keys = attribute_lookup_map.get(('path', 'project/dataset/title'), ())
        attribute_values = attribute_values_map.get(attribute_keys[0], ()) if len(attribute_keys) == 1 else ()
    return max((value.set_index for value in attribute_values), default=-1) + 1
