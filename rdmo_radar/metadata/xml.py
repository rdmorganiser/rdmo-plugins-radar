from xml.etree.ElementTree import Element

from .types import (
    Affiliation,
    Agent,
    Description,
    FundingReference,
    GeoLocation,
    Identifier,
    RadarMetadata,
    Resource,
    Rights,
    Software,
    SubjectArea,
)

ELEMENTS_NS = 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'


def to_xml_payload(metadata: RadarMetadata) -> dict:
    """Translate canonical RDDM metadata to the dictionary consumed by the XML renderer."""
    data = {}
    if metadata.identifier:
        data['identifier'] = metadata.identifier.value
        data['identifierType'] = metadata.identifier.identifier_type
    if metadata.alternate_identifiers:
        data['alternateIdentifiers'] = {'alternateIdentifier': [
            {
                'value': identifier.value,
                'alternateIdentifierType': identifier.identifier_type,
            }
            for identifier in metadata.alternate_identifiers
        ]}
    if metadata.related_identifiers:
        data['relatedIdentifiers'] = {'relatedIdentifier': [
            {
                'value': identifier.value,
                'relatedIdentifierType': identifier.identifier_type,
                'relationType': identifier.relation_type,
            }
            for identifier in metadata.related_identifiers
        ]}
    _serialize_agents(data, 'creators', 'creator', metadata.creators)
    _serialize_agents(data, 'contributors', 'contributor', metadata.contributors)
    if metadata.title:
        data['title'] = metadata.title
    if metadata.additional_titles:
        data['additionalTitles'] = [
            {'additionalTitle': title, 'additionalTitleType': 'Other'}
            for title in metadata.additional_titles
        ]
    if metadata.descriptions:
        data['descriptions'] = {'description': [
            {'value': description.value, 'descriptionType': description.description_type}
            for description in metadata.descriptions
        ]}
    if metadata.keywords:
        data['keywords'] = {'keyword': [{'value': keyword} for keyword in metadata.keywords]}
    if metadata.publishers:
        data['publishers'] = {'publisher': [_serialize_named_value(agent) for agent in metadata.publishers]}
    if metadata.production_year:
        data['productionYear'] = metadata.production_year
    if metadata.publication_year:
        data['publicationYear'] = metadata.publication_year
    if metadata.language:
        data['language'] = metadata.language
    if metadata.subject_areas:
        data['subjectAreas'] = {'subjectArea': [
            {
                'controlledSubjectAreaName': subject.controlled_name,
                'additionalSubjectAreaName': subject.additional_name,
            }
            for subject in metadata.subject_areas
        ]}
    if metadata.resource:
        data['resource'] = {
            'value': metadata.resource.value,
            'resourceType': metadata.resource.resource_type,
        }
    if metadata.geo_locations:
        data['geoLocations'] = {'geoLocation': [_serialize_geo_location(value) for value in metadata.geo_locations]}
    data_sources = [source for source in metadata.data_sources if source.resource_type]
    if data_sources:
        data['dataSources'] = {'dataSource': [
            {'value': source.value, 'dataSourceDetail': source.resource_type}
            for source in data_sources
        ]}
    if metadata.software:
        data['software'] = [_serialize_software(value) for value in metadata.software]
    if metadata.processing:
        data['dataProcessing'] = metadata.processing
    if metadata.rights:
        data['rights'] = {
            'controlledRights': metadata.rights.controlled,
            'additionalRights': metadata.rights.additional,
        }
    if metadata.rights_holders:
        data['rightsHolders'] = {
            'rightsHolder': [_serialize_named_value(agent) for agent in metadata.rights_holders]
        }
    if metadata.related_information:
        data['relatedInformations'] = [
            {'relatedInformation': value, 'relatedInformationType': 'Other'}
            for value in metadata.related_information
        ]
    if metadata.funding_references:
        data['fundingReferences'] = {
            'fundingReference': [_serialize_funding(value) for value in metadata.funding_references]
        }
    if metadata.version:
        data['version'] = metadata.version
    return data


def parse_xml(root: Element) -> RadarMetadata:
    """Parse RDDM 9.3 XML into canonical XML-spelled values."""
    metadata = RadarMetadata()
    identifier = _find(root, 'identifier')
    if identifier is not None and identifier.text:
        metadata.identifier = Identifier(identifier.text, identifier.get('identifierType'))
    metadata.alternate_identifiers.extend(_parse_identifiers(
        root, 'alternateIdentifiers', 'alternateIdentifier', 'alternateIdentifierType'
    ))
    metadata.related_identifiers.extend(_parse_identifiers(
        root, 'relatedIdentifiers', 'relatedIdentifier', 'relatedIdentifierType', with_relation=True
    ))
    metadata.creators.extend(_parse_agents(root, 'creators', 'creator'))
    metadata.contributors.extend(_parse_agents(root, 'contributors', 'contributor'))
    metadata.title = _text(root, 'title')
    metadata.additional_titles.extend(_texts(root, 'additionalTitles', 'additionalTitle'))
    for element in _findall(root, 'descriptions', 'description'):
        if element.text:
            metadata.descriptions.append(Description(element.text, element.get('descriptionType') or 'Abstract'))
    metadata.keywords.extend(_texts(root, 'keywords', 'keyword'))
    metadata.publishers.extend(_parse_named_values(root, 'publishers', 'publisher'))
    metadata.production_year = _text(root, 'productionYear')
    metadata.publication_year = _text(root, 'publicationYear')
    metadata.language = _text(root, 'language')
    for element in _findall(root, 'subjectAreas', 'subjectArea'):
        controlled = _text(element, 'controlledSubjectAreaName')
        if controlled:
            metadata.subject_areas.append(SubjectArea(controlled, _text(element, 'additionalSubjectAreaName')))
    resource = _find(root, 'resource')
    if resource is not None and resource.text:
        metadata.resource = Resource(resource.text, resource.get('resourceType'))
    metadata.geo_locations.extend(_parse_geo_locations(root))
    for element in _findall(root, 'dataSources', 'dataSource'):
        if element.text:
            metadata.data_sources.append(Resource(element.text, element.get('dataSourceDetail')))
    metadata.software.extend(_parse_software(root))
    metadata.processing.extend(_texts(root, 'processing', 'dataProcessing'))
    rights = _find(root, 'rights')
    if rights is not None:
        controlled = _text(rights, 'controlledRights')
        if controlled:
            metadata.rights = Rights(controlled, _text(rights, 'additionalRights'))
    metadata.rights_holders.extend(_parse_named_values(root, 'rightsHolders', 'rightsHolder'))
    metadata.related_information.extend(_texts(root, 'relatedInformations', 'relatedInformation'))
    metadata.funding_references.extend(_parse_funding(root))
    metadata.version = _text(root, 'version')
    return metadata


def _serialize_agents(data: dict, container: str, prefix: str, agents: list[Agent]) -> None:
    if not agents:
        return
    data[container] = {prefix: []}
    for agent in agents:
        item = {
            f'{prefix}Name': agent.name,
            'nameType': agent.name_type,
            'givenName': agent.given_name,
            'familyName': agent.family_name,
        }
        if prefix == 'contributor':
            item['contributorType'] = agent.contributor_type
        if agent.identifiers:
            item['nameIdentifier'] = [
                {'value': value.value, 'nameIdentifierScheme': value.identifier_type}
                for value in agent.identifiers
            ]
        if agent.affiliations:
            affiliations = [_serialize_affiliation(value) for value in agent.affiliations]
            item[f'{prefix}Affiliation'] = affiliations[0]
        data[container][prefix].append(item)


def _serialize_affiliation(affiliation: Affiliation) -> str | dict:
    if not affiliation.identifier:
        return affiliation.name
    return {
        'value': affiliation.name,
        'affiliationIdentifier': affiliation.identifier,
        'affiliationIdentifierScheme': affiliation.identifier_scheme,
    }


def _serialize_named_value(agent: Agent) -> str | dict:
    if not agent.identifiers:
        return agent.name
    identifier = agent.identifiers[0]
    return {
        'value': agent.name,
        'nameIdentifier': identifier.value,
        'nameIdentifierScheme': identifier.identifier_type,
    }


def _serialize_geo_location(location: GeoLocation) -> dict:
    return {
        'geoLocationCountry': location.country,
        'geoLocationRegion': location.region,
        'geoLocationPoint': {
            'latitude': location.latitude,
            'longitude': location.longitude,
        } if location.latitude and location.longitude else None,
    }


def _serialize_software(software: Software) -> dict:
    return {
        'type': software.software_type,
        'softwareName': software.name,
        'softwareVersion': software.version,
        'alternativeSoftwareName': software.alternative_name,
        'alternativeSoftwareVersion': software.alternative_version,
    }


def _serialize_funding(reference: FundingReference) -> dict:
    data = {
        'funderName': reference.funder_name,
        'awardNumber': reference.award_number,
        'awardURI': reference.award_uri,
        'awardTitle': reference.award_title,
    }
    if reference.funder_identifier:
        data['funderIdentifier'] = {
            'value': reference.funder_identifier.value,
            'type': reference.funder_identifier.identifier_type,
        }
    return data


def _parse_agents(root: Element, container: str, prefix: str) -> list[Agent]:
    agents = []
    for element in _findall(root, container, prefix):
        name = _text(element, f'{prefix}Name')
        if not name:
            continue
        identifiers = [
            Identifier(value.text, value.get('nameIdentifierScheme'))
            for value in element.findall(_q('nameIdentifier')) if value.text
        ]
        affiliation = _find(element, f'{prefix}Affiliation')
        affiliations = []
        if affiliation is not None and affiliation.text:
            affiliations.append(Affiliation(
                affiliation.text,
                affiliation.get('affiliationIdentifier'),
                affiliation.get('affiliationIdentifierScheme'),
            ))
        agents.append(Agent(
            name=name,
            given_name=_text(element, 'givenName'),
            family_name=_text(element, 'familyName'),
            name_type='Personal' if _text(element, 'givenName') or _text(element, 'familyName') else None,
            identifiers=identifiers,
            affiliations=affiliations,
            contributor_type=element.get('contributorType') if prefix == 'contributor' else None,
        ))
    return agents


def _parse_named_values(root: Element, container: str, name: str) -> list[Agent]:
    agents = []
    for element in _findall(root, container, name):
        if not element.text:
            continue
        identifier = element.get('nameIdentifier')
        agents.append(Agent(
            name=element.text,
            identifiers=[Identifier(identifier, element.get('nameIdentifierScheme'))] if identifier else [],
        ))
    return agents


def _parse_identifiers(
    root: Element,
    container: str,
    name: str,
    type_attribute: str,
    *,
    with_relation: bool = False,
) -> list[Identifier]:
    return [
        Identifier(
            element.text,
            element.get(type_attribute),
            element.get('relationType') if with_relation else None,
        )
        for element in _findall(root, container, name) if element.text
    ]


def _parse_geo_locations(root: Element) -> list[GeoLocation]:
    locations = []
    for element in _findall(root, 'geoLocations', 'geoLocation'):
        point = _find(element, 'geoLocationPoint')
        locations.append(GeoLocation(
            country=_text(element, 'geoLocationCountry'),
            region=_text(element, 'geoLocationRegion'),
            latitude=_text(point, 'latitude') if point is not None else None,
            longitude=_text(point, 'longitude') if point is not None else None,
        ))
    return locations


def _parse_software(root: Element) -> list[Software]:
    software = []
    for element in _findall(root, 'software', 'softwareType'):
        name = _find(element, 'softwareName')
        alternative = _find(element, 'alternativeSoftwareName')
        if name is not None and name.text:
            software.append(Software(
                name.text,
                element.get('type'),
                name.get('softwareVersion'),
                alternative.text if alternative is not None else None,
                alternative.get('alternativeSoftwareVersion') if alternative is not None else None,
            ))
    return software


def _parse_funding(root: Element) -> list[FundingReference]:
    references = []
    for element in _findall(root, 'fundingReferences', 'fundingReference'):
        identifier = _find(element, 'funderIdentifier')
        references.append(FundingReference(
            funder_name=_text(element, 'funderName'),
            funder_identifier=Identifier(identifier.text, identifier.get('type'))
            if identifier is not None and identifier.text else None,
            award_number=_text(element, 'awardNumber'),
            award_uri=_text(element, 'awardURI'),
            award_title=_text(element, 'awardTitle'),
        ))
    return references


def _find(root: Element | None, name: str) -> Element | None:
    return root.find(_q(name)) if root is not None else None


def _findall(root: Element, container: str, name: str) -> list[Element]:
    parent = _find(root, container)
    return list(parent.findall(_q(name))) if parent is not None else []


def _text(root: Element | None, name: str) -> str | None:
    element = _find(root, name)
    return element.text if element is not None else None


def _texts(root: Element, container: str, name: str) -> list[str]:
    return [element.text for element in _findall(root, container, name) if element.text]


def _q(name: str) -> str:
    return f'{{{ELEMENTS_NS}}}{name}'
