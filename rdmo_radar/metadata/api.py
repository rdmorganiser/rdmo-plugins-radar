from .constants import to_api_value
from .types import Agent, RadarMetadata
from .xml import to_xml_payload


def to_api_payload(metadata: RadarMetadata) -> dict:
    """Translate canonical RDDM metadata to the RADAR REST representation."""
    data = to_xml_payload(metadata)
    _convert(data, 'identifierType')
    _convert_items(data, 'alternateIdentifiers', 'alternateIdentifier', 'alternateIdentifierType')
    _convert_items(data, 'relatedIdentifiers', 'relatedIdentifier', 'relatedIdentifierType', 'relationType')
    _convert_agents(data, 'creators', 'creator', metadata.creators)
    _convert_agents(data, 'contributors', 'contributor', metadata.contributors)
    for title in data.get('additionalTitles', []):
        title['additionalTitleType'] = 'OTHER'
    _convert_items(data, 'descriptions', 'description', 'descriptionType')
    _convert(data, 'language')
    _convert_items(data, 'subjectAreas', 'subjectArea', 'controlledSubjectAreaName')
    if data.get('resource'):
        _convert(data['resource'], 'resourceType')
    if metadata.data_sources:
        data['dataSources'] = {'dataSource': [
            {'value': source.value, 'dataSourceDetail': to_api_value(source.resource_type)}
            for source in metadata.data_sources
        ]}
    for software in data.get('software', []):
        _convert(software, 'type')
    if data.get('rights'):
        _convert(data['rights'], 'controlledRights')
    _convert_named_values(data, 'publishers', 'publisher')
    _convert_named_values(data, 'rightsHolders', 'rightsHolder')
    for information in data.get('relatedInformations', []):
        information['relatedInformationType'] = 'OTHER'
    for reference in data.get('fundingReferences', {}).get('fundingReference', []):
        if reference.get('funderIdentifier'):
            _convert(reference['funderIdentifier'], 'type')
    return data


def _convert(data: dict, key: str) -> None:
    if key in data:
        data[key] = to_api_value(data[key])


def _convert_items(data: dict, container: str, item: str, *keys: str) -> None:
    for value in data.get(container, {}).get(item, []):
        for key in keys:
            _convert(value, key)


def _convert_agents(data: dict, container: str, prefix: str, agents: list[Agent]) -> None:
    values = data.get(container, {}).get(prefix, [])
    for value, agent in zip(values, agents, strict=True):
        _convert(value, 'nameType')
        if prefix == 'contributor':
            _convert(value, 'contributorType')
        for identifier in value.get('nameIdentifier', []):
            _convert(identifier, 'nameIdentifierScheme')
        if agent.affiliations:
            value[f'{prefix}Affiliation'] = [
                _convert_affiliation(affiliation) for affiliation in agent.affiliations
            ]


def _convert_affiliation(affiliation) -> str | dict:
    if not affiliation.identifier:
        return affiliation.name
    return {
        'value': affiliation.name,
        'affiliationIdentifier': affiliation.identifier,
        'affiliationIdentifierScheme': to_api_value(affiliation.identifier_scheme),
    }


def _convert_named_values(data: dict, container: str, item: str) -> None:
    for value in data.get(container, {}).get(item, []):
        if isinstance(value, dict):
            _convert(value, 'nameIdentifierScheme')
