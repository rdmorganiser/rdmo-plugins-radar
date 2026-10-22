"""RADAR REST serialization, independent of the XML renderer's payload format."""

from .constants import to_api_value
from .provenance import json_leaves, record_binding
from .types import Affiliation, FundingReference, GeoLocation, PersonOrOrganization, RadarMetadata, Software


def compute_radar_payload(
    metadata: RadarMetadata,
    *,
    responsible_email: str,
    timestamp: int,
    record_output=None,
) -> dict:
    """Build the RADAR request with an explicit millisecond timestamp, independent of a request/session."""
    payload = {
        'technicalMetadata': {
            'retentionPeriod': 10,
            'archiveDate': timestamp,
            'publishDate': timestamp,
            'responsibleEmail': responsible_email,
            'schema': {'key': 'RDDM', 'version': '9.3'},
        },
        'descriptiveMetadata': to_api_payload(metadata, record_output=record_output),
    }
    if record_output is not None:
        for path, value in json_leaves(payload['technicalMetadata'], '/technicalMetadata'):
            if path.endswith('/responsibleEmail'):
                reason = 'Export responsible email'
            elif path.endswith('Date'):
                reason = 'Export clock in milliseconds'
            else:
                reason = 'RADAR technical default'
            record_binding(record_output, f'$technical{path}', path, value, reason)
    return payload


def to_api_payload(metadata: RadarMetadata, *, record_output=None) -> dict:
    """Build descriptive metadata for RDDM 9.3; omit unavailable draft fields."""
    data = {}
    path = '/descriptiveMetadata'
    if metadata.identifier:
        identifier = metadata.identifier
        data['identifier'] = _present(
            value=identifier.value,
            identifierType=to_api_value(identifier.identifier_type),
        )
        record_binding(record_output, 'identifier.value', f'{path}/identifier/value', identifier.value)
        record_binding(
            record_output,
            'identifier.identifier_type',
            f'{path}/identifier/identifierType',
            data['identifier'].get('identifierType'),
        )
    for field, container, item, type_field in (
        ('alternate_identifiers', 'alternateIdentifiers', 'alternateIdentifier', 'alternateIdentifierType'),
        ('related_identifiers', 'relatedIdentifiers', 'relatedIdentifier', 'relatedIdentifierType'),
    ):
        identifiers = getattr(metadata, field)
        if not identifiers:
            continue
        items = []
        for index, identifier in enumerate(identifiers):
            # alternateIdentifierType is free text, not a controlled enum.
            identifier_type = identifier.identifier_type
            if field == 'related_identifiers':
                identifier_type = to_api_value(identifier_type)
            value = _present(value=identifier.value, **{type_field: identifier_type})
            target = f'{field}[{index}]'
            output_path = f'{path}/{container}/{item}/{index}'
            record_binding(record_output, f'{target}.value', f'{output_path}/value', identifier.value)
            record_binding(record_output, f'{target}.identifier_type', f'{output_path}/{type_field}', identifier_type)
            if field == 'related_identifiers':
                relation_type = to_api_value(identifier.relation_type)
                value.update(_present(relationType=relation_type))
                record_binding(record_output, f'{target}.relation_type', f'{output_path}/relationType', relation_type)
            items.append(value)
        data[container] = {item: items}
    for container, item in (('creators', 'creator'), ('contributors', 'contributor')):
        people = getattr(metadata, container)
        if people:
            data[container] = {
                item: [
                    _person_or_organization(
                        person,
                        item,
                        target=f'{container}[{index}]',
                        path=f'{path}/{container}/{item}/{index}',
                        record_output=record_output,
                    )
                    for index, person in enumerate(people)
                ]
            }
    if metadata.title:
        data['title'] = metadata.title
        record_binding(record_output, 'title', f'{path}/title', data['title'])
    if metadata.additional_titles:
        items = []
        for index, title in enumerate(metadata.additional_titles):
            items.append({'value': title, 'additionalTitleType': 'OTHER'})
            output_path = f'{path}/additionalTitles/additionalTitle/{index}'
            record_binding(record_output, f'additional_titles[{index}]', f'{output_path}/value', title)
            record_binding(
                record_output,
                '$additionalTitleType',
                f'{output_path}/additionalTitleType',
                'OTHER',
                'Serializer title category',
            )
        data['additionalTitles'] = {'additionalTitle': items}
    if metadata.descriptions:
        items = []
        for index, description in enumerate(metadata.descriptions):
            description_type = to_api_value(description.description_type)
            items.append({'value': description.value, 'descriptionType': description_type})
            target = f'descriptions[{index}]'
            output_path = f'{path}/descriptions/description/{index}'
            record_binding(record_output, f'{target}.value', f'{output_path}/value', description.value)
            record_binding(
                record_output, f'{target}.description_type', f'{output_path}/descriptionType', description_type
            )
        data['descriptions'] = {'description': items}
    if metadata.keywords:
        data['keywords'] = {'keyword': [{'value': value} for value in metadata.keywords]}
        for index, value in enumerate(metadata.keywords):
            record_binding(record_output, f'keywords[{index}]', f'{path}/keywords/keyword/{index}/value', value)
    if metadata.publishers:
        data['publishers'] = {
            'publisher': [
                _named_value(
                    person,
                    target=f'publishers[{index}]',
                    path=f'{path}/publishers/publisher/{index}',
                    record_output=record_output,
                )
                for index, person in enumerate(metadata.publishers)
            ]
        }
    for field, name in (
        ('production_year', 'productionYear'),
        ('publication_year', 'publicationYear'),
        ('language', 'language'),
    ):
        value = getattr(metadata, field)
        if value:
            data[name] = to_api_value(value) if field == 'language' else value
            record_binding(record_output, field, f'{path}/{name}', data[name])
    if metadata.subject_areas:
        items = []
        for index, subject in enumerate(metadata.subject_areas):
            value = _present(
                controlledSubjectAreaName=to_api_value(subject.controlled_name),
                additionalSubjectAreaName=subject.additional_name,
            )
            items.append(value)
            target = f'subject_areas[{index}]'
            output_path = f'{path}/subjectAreas/subjectArea/{index}'
            record_binding(
                record_output,
                f'{target}.controlled_name',
                f'{output_path}/controlledSubjectAreaName',
                value.get('controlledSubjectAreaName'),
            )
            record_binding(
                record_output,
                f'{target}.additional_name',
                f'{output_path}/additionalSubjectAreaName',
                subject.additional_name,
            )
        data['subjectAreas'] = {'subjectArea': items}
    if metadata.resource:
        data['resource'] = _present(
            value=metadata.resource.value,
            resourceType=to_api_value(metadata.resource.resource_type),
        )
        record_binding(record_output, 'resource.value', f'{path}/resource/value', data['resource'].get('value'))
        record_binding(
            record_output,
            'resource.resource_type',
            f'{path}/resource/resourceType',
            data['resource'].get('resourceType'),
        )
    if metadata.geo_locations:
        data['geoLocations'] = {
            'geoLocation': [
                _geo_location(
                    location,
                    target=f'geo_locations[{index}]',
                    path=f'{path}/geoLocations/geoLocation/{index}',
                    record_output=record_output,
                )
                for index, location in enumerate(metadata.geo_locations)
            ]
        }
    if metadata.data_sources:
        items = []
        for index, source in enumerate(metadata.data_sources):
            detail = to_api_value(source.resource_type)
            items.append(_present(value=source.value, dataSourceDetail=detail))
            target = f'data_sources[{index}]'
            output_path = f'{path}/dataSources/dataSource/{index}'
            record_binding(record_output, f'{target}.value', f'{output_path}/value', source.value)
            record_binding(record_output, f'{target}.resource_type', f'{output_path}/dataSourceDetail', detail)
        data['dataSources'] = {'dataSource': items}
    if metadata.software:
        data['software'] = {
            'softwareType': [
                _software(
                    software,
                    target=f'software[{index}]',
                    path=f'{path}/software/softwareType/{index}',
                    record_output=record_output,
                )
                for index, software in enumerate(metadata.software)
            ]
        }
    if metadata.processing:
        data['processing'] = {'dataProcessing': list(metadata.processing)}
        for index, value in enumerate(metadata.processing):
            record_binding(record_output, f'processing[{index}]', f'{path}/processing/dataProcessing/{index}', value)
    if metadata.rights:
        data['rights'] = _present(
            controlledRights=to_api_value(metadata.rights.controlled),
            additionalRights=metadata.rights.additional,
        )
        record_binding(
            record_output,
            'rights.controlled',
            f'{path}/rights/controlledRights',
            data['rights'].get('controlledRights'),
        )
        record_binding(
            record_output, 'rights.additional', f'{path}/rights/additionalRights', metadata.rights.additional
        )
    if metadata.rights_holders:
        data['rightsHolders'] = {
            'rightsHolder': [
                _named_value(
                    person,
                    target=f'rights_holders[{index}]',
                    path=f'{path}/rightsHolders/rightsHolder/{index}',
                    record_output=record_output,
                )
                for index, person in enumerate(metadata.rights_holders)
            ]
        }
    if metadata.related_information:
        items = []
        for index, value in enumerate(metadata.related_information):
            # relatedInformationType is free text, unlike additionalTitleType.
            items.append({'value': value, 'relatedInformationType': 'Other'})
            output_path = f'{path}/relatedInformations/relatedInformation/{index}'
            record_binding(record_output, f'related_information[{index}]', f'{output_path}/value', value)
            record_binding(
                record_output,
                '$relatedInformationType',
                f'{output_path}/relatedInformationType',
                'Other',
                'Serializer information category',
            )
        data['relatedInformations'] = {'relatedInformation': items}
    if metadata.funding_references:
        data['fundingReferences'] = {
            'fundingReference': [
                _funding(
                    reference,
                    target=f'funding_references[{index}]',
                    path=f'{path}/fundingReferences/fundingReference/{index}',
                    record_output=record_output,
                )
                for index, reference in enumerate(metadata.funding_references)
            ]
        }
    if metadata.version:
        data['version'] = metadata.version
        record_binding(record_output, 'version', f'{path}/version', data['version'])
    return data


def _present(**values) -> dict:
    return {key: value for key, value in values.items() if value is not None}


def _person_or_organization(
    person_or_organization: PersonOrOrganization,
    prefix: str,
    *,
    target='',
    path='',
    record_output=None,
) -> dict:
    data = _present(
        **{
            f'{prefix}Name': person_or_organization.name,
            'nameType': to_api_value(person_or_organization.name_type),
            'givenName': person_or_organization.given_name,
            'familyName': person_or_organization.family_name,
        }
    )
    for field, name in (
        ('name', f'{prefix}Name'),
        ('name_type', 'nameType'),
        ('given_name', 'givenName'),
        ('family_name', 'familyName'),
    ):
        record_binding(record_output, f'{target}.{field}', f'{path}/{name}', data.get(name))
    if prefix == 'contributor' and person_or_organization.contributor_type:
        data['contributorType'] = to_api_value(person_or_organization.contributor_type)
        record_binding(record_output, f'{target}.contributor_type', f'{path}/contributorType', data['contributorType'])
    if person_or_organization.identifiers:
        identifiers = []
        for index, identifier in enumerate(person_or_organization.identifiers):
            scheme = to_api_value(identifier.identifier_type)
            identifiers.append(_present(value=identifier.value, nameIdentifierScheme=scheme))
            output_path = f'{path}/nameIdentifier/{index}'
            record_binding(
                record_output, f'{target}.identifiers[{index}].value', f'{output_path}/value', identifier.value
            )
            record_binding(
                record_output,
                f'{target}.identifiers[{index}].identifier_type',
                f'{output_path}/nameIdentifierScheme',
                scheme,
            )
        data['nameIdentifier'] = identifiers
    # RDDM 9.3 has one affiliation per person or organization, including in REST.
    if person_or_organization.affiliations:
        data[f'{prefix}Affiliation'] = _affiliation(
            person_or_organization.affiliations[0],
            target=f'{target}.affiliations[0]',
            path=f'{path}/{prefix}Affiliation',
            record_output=record_output,
        )
    return data


def _affiliation(affiliation: Affiliation, *, target='', path='', record_output=None) -> dict:
    data = _present(
        value=affiliation.name,
        affiliationIdentifier=affiliation.identifier,
        affiliationIdentifierScheme=to_api_value(affiliation.identifier_scheme),
    )
    record_binding(record_output, f'{target}.name', f'{path}/value', affiliation.name)
    record_binding(record_output, f'{target}.identifier', f'{path}/affiliationIdentifier', affiliation.identifier)
    record_binding(
        record_output,
        f'{target}.identifier_scheme',
        f'{path}/affiliationIdentifierScheme',
        data.get('affiliationIdentifierScheme'),
    )
    return data


def _named_value(person_or_organization: PersonOrOrganization, *, target='', path='', record_output=None) -> dict:
    data = {'value': person_or_organization.name}
    record_binding(record_output, f'{target}.name', f'{path}/value', data['value'])
    if person_or_organization.identifiers:
        identifier = person_or_organization.identifiers[0]
        scheme = to_api_value(identifier.identifier_type)
        data.update(_present(nameIdentifier=identifier.value, nameIdentifierScheme=scheme))
        record_binding(record_output, f'{target}.identifiers[0].value', f'{path}/nameIdentifier', identifier.value)
        record_binding(
            record_output, f'{target}.identifiers[0].identifier_type', f'{path}/nameIdentifierScheme', scheme
        )
    return data


def _geo_location(location: GeoLocation, *, target='', path='', record_output=None) -> dict:
    data = _present(geoLocationCountry=to_api_value(location.country), geoLocationRegion=location.region)
    record_binding(record_output, f'{target}.country', f'{path}/geoLocationCountry', data.get('geoLocationCountry'))
    record_binding(record_output, f'{target}.region', f'{path}/geoLocationRegion', location.region)
    if location.latitude is not None and location.longitude is not None:
        data['geoLocationPoint'] = {'latitude': float(location.latitude), 'longitude': float(location.longitude)}
        for field, value in data['geoLocationPoint'].items():
            record_binding(record_output, f'{target}.{field}', f'{path}/geoLocationPoint/{field}', value)
    return data


def _software(software: Software, *, target='', path='', record_output=None) -> dict:
    data = _present(type=to_api_value(software.software_type))
    data['softwareName'] = [_present(value=software.name, softwareVersion=software.version)]
    record_binding(record_output, f'{target}.software_type', f'{path}/type', data.get('type'))
    record_binding(record_output, f'{target}.name', f'{path}/softwareName/0/value', software.name)
    record_binding(record_output, f'{target}.version', f'{path}/softwareName/0/softwareVersion', software.version)
    if software.alternative_name:
        data['alternativeSoftwareName'] = [
            _present(value=software.alternative_name, alternativeSoftwareVersion=software.alternative_version)
        ]
        record_binding(
            record_output,
            f'{target}.alternative_name',
            f'{path}/alternativeSoftwareName/0/value',
            software.alternative_name,
        )
        record_binding(
            record_output,
            f'{target}.alternative_version',
            f'{path}/alternativeSoftwareName/0/alternativeSoftwareVersion',
            software.alternative_version,
        )
    return data


def _funding(reference: FundingReference, *, target='', path='', record_output=None) -> dict:
    data = _present(
        funderName=reference.funder_name,
        awardNumber=reference.award_number,
        awardURI=reference.award_uri,
        awardTitle=reference.award_title,
    )
    for field, name in (
        ('funder_name', 'funderName'),
        ('award_number', 'awardNumber'),
        ('award_uri', 'awardURI'),
        ('award_title', 'awardTitle'),
    ):
        record_binding(record_output, f'{target}.{field}', f'{path}/{name}', data.get(name))
    if reference.funder_identifier:
        identifier = reference.funder_identifier
        scheme = to_api_value(identifier.identifier_type)
        data['funderIdentifier'] = _present(value=identifier.value, type=scheme)
        record_binding(
            record_output, f'{target}.funder_identifier.value', f'{path}/funderIdentifier/value', identifier.value
        )
        record_binding(
            record_output, f'{target}.funder_identifier.identifier_type', f'{path}/funderIdentifier/type', scheme
        )
    return data
