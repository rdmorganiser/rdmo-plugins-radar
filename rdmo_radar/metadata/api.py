"""RADAR REST serialization, independent of the XML renderer's payload format."""

from .constants import to_api_value
from .types import Affiliation, Agent, FundingReference, GeoLocation, RadarMetadata, Software


def to_api_payload(metadata: RadarMetadata) -> dict:
    """Build descriptive metadata for RDDM 9.3; omit unavailable draft fields."""
    data = {}
    if metadata.identifier:
        data['identifier'] = _present(
            value=metadata.identifier.value,
            identifierType=to_api_value(metadata.identifier.identifier_type),
        )
    if metadata.alternate_identifiers:
        # alternateIdentifierType is free text, not a controlled enum.
        data['alternateIdentifiers'] = {'alternateIdentifier': [
            _present(value=value.value, alternateIdentifierType=value.identifier_type)
            for value in metadata.alternate_identifiers
        ]}
    if metadata.related_identifiers:
        data['relatedIdentifiers'] = {'relatedIdentifier': [
            _present(value=value.value, relatedIdentifierType=to_api_value(value.identifier_type),
                     relationType=to_api_value(value.relation_type))
            for value in metadata.related_identifiers
        ]}
    if metadata.creators:
        data['creators'] = {'creator': [_agent(value, 'creator') for value in metadata.creators]}
    if metadata.contributors:
        data['contributors'] = {'contributor': [_agent(value, 'contributor') for value in metadata.contributors]}
    if metadata.title:
        data['title'] = metadata.title
    if metadata.additional_titles:
        data['additionalTitles'] = {'additionalTitle': [
            {'value': value, 'additionalTitleType': 'OTHER'} for value in metadata.additional_titles
        ]}
    if metadata.descriptions:
        data['descriptions'] = {'description': [
            {'value': value.value, 'descriptionType': to_api_value(value.description_type)}
            for value in metadata.descriptions
        ]}
    if metadata.keywords:
        data['keywords'] = {'keyword': [{'value': value} for value in metadata.keywords]}
    if metadata.publishers:
        data['publishers'] = {'publisher': [_named_value(value) for value in metadata.publishers]}
    if metadata.production_year:
        data['productionYear'] = metadata.production_year
    if metadata.publication_year:
        data['publicationYear'] = metadata.publication_year
    if metadata.language:
        data['language'] = to_api_value(metadata.language)
    if metadata.subject_areas:
        data['subjectAreas'] = {'subjectArea': [
            _present(controlledSubjectAreaName=to_api_value(value.controlled_name),
                     additionalSubjectAreaName=value.additional_name)
            for value in metadata.subject_areas
        ]}
    if metadata.resource:
        data['resource'] = _present(value=metadata.resource.value,
                                    resourceType=to_api_value(metadata.resource.resource_type))
    if metadata.geo_locations:
        data['geoLocations'] = {'geoLocation': [_geo_location(value) for value in metadata.geo_locations]}
    if metadata.data_sources:
        data['dataSources'] = {'dataSource': [
            _present(value=value.value, dataSourceDetail=to_api_value(value.resource_type))
            for value in metadata.data_sources
        ]}
    if metadata.software:
        data['software'] = {'softwareType': [_software(value) for value in metadata.software]}
    if metadata.processing:
        data['processing'] = {'dataProcessing': list(metadata.processing)}
    if metadata.rights:
        data['rights'] = _present(controlledRights=to_api_value(metadata.rights.controlled),
                                  additionalRights=metadata.rights.additional)
    if metadata.rights_holders:
        data['rightsHolders'] = {'rightsHolder': [_named_value(value) for value in metadata.rights_holders]}
    if metadata.related_information:
        # relatedInformationType is free text, unlike additionalTitleType.
        data['relatedInformations'] = {'relatedInformation': [
            {'value': value, 'relatedInformationType': 'Other'} for value in metadata.related_information
        ]}
    if metadata.funding_references:
        data['fundingReferences'] = {'fundingReference': [_funding(value) for value in metadata.funding_references]}
    if metadata.version:
        data['version'] = metadata.version
    return data


def _present(**values) -> dict:
    return {key: value for key, value in values.items() if value is not None}


def _agent(agent: Agent, prefix: str) -> dict:
    data = _present(**{
        f'{prefix}Name': agent.name,
        'nameType': to_api_value(agent.name_type),
        'givenName': agent.given_name,
        'familyName': agent.family_name,
    })
    if prefix == 'contributor' and agent.contributor_type:
        data['contributorType'] = to_api_value(agent.contributor_type)
    if agent.identifiers:
        data['nameIdentifier'] = [
            _present(value=value.value, nameIdentifierScheme=to_api_value(value.identifier_type))
            for value in agent.identifiers
        ]
    # RDDM 9.3 has one affiliation per agent, including in REST.
    if agent.affiliations:
        data[f'{prefix}Affiliation'] = _affiliation(agent.affiliations[0])
    return data


def _affiliation(affiliation: Affiliation) -> dict:
    return _present(value=affiliation.name, affiliationIdentifier=affiliation.identifier,
                    affiliationIdentifierScheme=to_api_value(affiliation.identifier_scheme))


def _named_value(agent: Agent) -> dict:
    data = {'value': agent.name}
    if agent.identifiers:
        identifier = agent.identifiers[0]
        data.update(_present(nameIdentifier=identifier.value,
                             nameIdentifierScheme=to_api_value(identifier.identifier_type)))
    return data


def _geo_location(location: GeoLocation) -> dict:
    data = _present(geoLocationCountry=to_api_value(location.country), geoLocationRegion=location.region)
    if location.latitude is not None and location.longitude is not None:
        data['geoLocationPoint'] = {'latitude': float(location.latitude), 'longitude': float(location.longitude)}
    return data


def _software(software: Software) -> dict:
    data = _present(type=to_api_value(software.software_type))
    data['softwareName'] = [_present(value=software.name, softwareVersion=software.version)]
    if software.alternative_name:
        data['alternativeSoftwareName'] = [
            _present(value=software.alternative_name, alternativeSoftwareVersion=software.alternative_version)
        ]
    return data


def _funding(reference: FundingReference) -> dict:
    data = _present(funderName=reference.funder_name, awardNumber=reference.award_number,
                    awardURI=reference.award_uri, awardTitle=reference.award_title)
    if reference.funder_identifier:
        data['funderIdentifier'] = _present(value=reference.funder_identifier.value,
                                           type=to_api_value(reference.funder_identifier.identifier_type))
    return data
