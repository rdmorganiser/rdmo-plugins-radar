from xml.etree.ElementTree import Element

from .provenance import record_binding
from .types import (
    Affiliation,
    Description,
    FundingReference,
    GeoLocation,
    Identifier,
    PersonOrOrganization,
    RadarMetadata,
    Resource,
    Rights,
    Software,
    SubjectArea,
)

ELEMENTS_NS = 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'


def to_xml_payload(metadata: RadarMetadata, *, record_output=None) -> dict:
    """Translate canonical RDDM metadata to the dictionary consumed by the XML renderer."""
    data = {}
    path = '/radar:radarDataset'
    if metadata.identifier:
        data['identifier'] = metadata.identifier.value
        data['identifierType'] = metadata.identifier.identifier_type
        record_binding(record_output, 'identifier.value', f'{path}/re:identifier', data['identifier'])
        record_binding(
            record_output, 'identifier.identifier_type', f'{path}/re:identifier/@identifierType', data['identifierType']
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
            value = {'value': identifier.value, type_field: identifier.identifier_type}
            target = f'{field}[{index}]'
            output_path = f'{path}/re:{container}/re:{item}[{index + 1}]'
            record_binding(record_output, f'{target}.value', output_path, identifier.value)
            record_binding(
                record_output, f'{target}.identifier_type', f'{output_path}/@{type_field}', identifier.identifier_type
            )
            if field == 'related_identifiers':
                value['relationType'] = identifier.relation_type
                record_binding(
                    record_output, f'{target}.relation_type', f'{output_path}/@relationType', identifier.relation_type
                )
            items.append(value)
        data[container] = {item: items}
    _serialize_people_and_organizations(data, 'creators', 'creator', metadata.creators, record_output=record_output)
    _serialize_people_and_organizations(
        data, 'contributors', 'contributor', metadata.contributors, record_output=record_output
    )
    if metadata.title:
        data['title'] = metadata.title
        record_binding(record_output, 'title', f'{path}/re:title', data['title'])
    if metadata.additional_titles:
        items = []
        for index, title in enumerate(metadata.additional_titles):
            items.append({'additionalTitle': title, 'additionalTitleType': 'Other'})
            output_path = f'{path}/re:additionalTitles/re:additionalTitle[{index + 1}]'
            record_binding(record_output, f'additional_titles[{index}]', output_path, title)
            record_binding(
                record_output,
                '$additionalTitleType',
                f'{output_path}/@additionalTitleType',
                'Other',
                'Serializer title category',
            )
        data['additionalTitles'] = items
    if metadata.descriptions:
        items = []
        for index, description in enumerate(metadata.descriptions):
            items.append({'value': description.value, 'descriptionType': description.description_type})
            target = f'descriptions[{index}]'
            output_path = f'{path}/re:descriptions/re:description[{index + 1}]'
            record_binding(record_output, f'{target}.value', output_path, description.value)
            record_binding(
                record_output,
                f'{target}.description_type',
                f'{output_path}/@descriptionType',
                description.description_type,
            )
        data['descriptions'] = {'description': items}
    if metadata.keywords:
        data['keywords'] = {'keyword': [{'value': keyword} for keyword in metadata.keywords]}
        for index, value in enumerate(metadata.keywords):
            record_binding(record_output, f'keywords[{index}]', f'{path}/re:keywords/re:keyword[{index + 1}]', value)
    if metadata.publishers:
        data['publishers'] = {
            'publisher': [
                _serialize_named_value(
                    publisher,
                    target=f'publishers[{index}]',
                    path=f'{path}/re:publishers/re:publisher[{index + 1}]',
                    record_output=record_output,
                )
                for index, publisher in enumerate(metadata.publishers)
            ]
        }
    for field, name in (
        ('production_year', 'productionYear'),
        ('publication_year', 'publicationYear'),
        ('language', 'language'),
    ):
        value = getattr(metadata, field)
        if value:
            data[name] = value
            record_binding(record_output, field, f'{path}/re:{name}', value)
    if metadata.subject_areas:
        items = []
        for index, subject in enumerate(metadata.subject_areas):
            items.append(
                {
                    'controlledSubjectAreaName': subject.controlled_name,
                    'additionalSubjectAreaName': subject.additional_name,
                }
            )
            target = f'subject_areas[{index}]'
            output_path = f'{path}/re:subjectAreas/re:subjectArea[{index + 1}]'
            record_binding(
                record_output,
                f'{target}.controlled_name',
                f'{output_path}/re:controlledSubjectAreaName',
                subject.controlled_name,
            )
            record_binding(
                record_output,
                f'{target}.additional_name',
                f'{output_path}/re:additionalSubjectAreaName',
                subject.additional_name,
            )
        data['subjectAreas'] = {'subjectArea': items}
    if metadata.resource:
        data['resource'] = {
            'value': metadata.resource.value,
            'resourceType': metadata.resource.resource_type,
        }
        record_binding(record_output, 'resource.value', f'{path}/re:resource', metadata.resource.value)
        record_binding(
            record_output,
            'resource.resource_type',
            f'{path}/re:resource/@resourceType',
            metadata.resource.resource_type,
        )
    if metadata.geo_locations:
        data['geoLocations'] = {
            'geoLocation': [
                _serialize_geo_location(
                    location,
                    target=f'geo_locations[{index}]',
                    path=f'{path}/re:geoLocations/re:geoLocation[{index + 1}]',
                    record_output=record_output,
                )
                for index, location in enumerate(metadata.geo_locations)
            ]
        }
    data_sources = []
    for index, source in enumerate(metadata.data_sources):
        if not source.resource_type:
            continue
        data_sources.append({'value': source.value, 'dataSourceDetail': source.resource_type})
        target = f'data_sources[{index}]'
        output_path = f'{path}/re:dataSources/re:dataSource[{len(data_sources)}]'
        record_binding(record_output, f'{target}.value', output_path, source.value)
        record_binding(
            record_output, f'{target}.resource_type', f'{output_path}/@dataSourceDetail', source.resource_type
        )
    if data_sources:
        data['dataSources'] = {'dataSource': data_sources}
    if metadata.software:
        data['software'] = [
            _serialize_software(
                software,
                target=f'software[{index}]',
                path=f'{path}/re:software/re:softwareType[{index + 1}]',
                record_output=record_output,
            )
            for index, software in enumerate(metadata.software)
        ]
    if metadata.processing:
        data['dataProcessing'] = metadata.processing
        for index, value in enumerate(metadata.processing):
            record_binding(
                record_output, f'processing[{index}]', f'{path}/re:processing/re:dataProcessing[{index + 1}]', value
            )
    if metadata.rights:
        data['rights'] = {
            'controlledRights': metadata.rights.controlled,
            'additionalRights': metadata.rights.additional,
        }
        record_binding(
            record_output, 'rights.controlled', f'{path}/re:rights/re:controlledRights', metadata.rights.controlled
        )
        record_binding(
            record_output, 'rights.additional', f'{path}/re:rights/re:additionalRights', metadata.rights.additional
        )
    if metadata.rights_holders:
        data['rightsHolders'] = {
            'rightsHolder': [
                _serialize_named_value(
                    person,
                    target=f'rights_holders[{index}]',
                    path=f'{path}/re:rightsHolders/re:rightsHolder[{index + 1}]',
                    record_output=record_output,
                )
                for index, person in enumerate(metadata.rights_holders)
            ]
        }
    if metadata.related_information:
        items = []
        for index, value in enumerate(metadata.related_information):
            items.append({'relatedInformation': value, 'relatedInformationType': 'Other'})
            output_path = f'{path}/re:relatedInformations/re:relatedInformation[{index + 1}]'
            record_binding(record_output, f'related_information[{index}]', output_path, value)
            record_binding(
                record_output,
                '$relatedInformationType',
                f'{output_path}/@relatedInformationType',
                'Other',
                'Serializer information category',
            )
        data['relatedInformations'] = items
    if metadata.funding_references:
        data['fundingReferences'] = {
            'fundingReference': [
                _serialize_funding(
                    reference,
                    target=f'funding_references[{index}]',
                    path=f'{path}/re:fundingReferences/re:fundingReference[{index + 1}]',
                    record_output=record_output,
                )
                for index, reference in enumerate(metadata.funding_references)
            ]
        }
    if metadata.version:
        data['version'] = metadata.version
        record_binding(record_output, 'version', f'{path}/re:version', data['version'])
    return data


def parse_xml(root: Element) -> RadarMetadata:
    """Parse RDDM 9.3 XML into canonical XML-spelled values."""
    metadata = RadarMetadata()
    identifier = _find(root, 'identifier')
    if identifier is not None and identifier.text:
        metadata.identifier = Identifier(identifier.text, identifier.get('identifierType'))
    metadata.alternate_identifiers.extend(
        _parse_identifiers(root, 'alternateIdentifiers', 'alternateIdentifier', 'alternateIdentifierType')
    )
    metadata.related_identifiers.extend(
        _parse_identifiers(root, 'relatedIdentifiers', 'relatedIdentifier', 'relatedIdentifierType', with_relation=True)
    )
    metadata.creators.extend(_parse_people_and_organizations(root, 'creators', 'creator'))
    metadata.contributors.extend(_parse_people_and_organizations(root, 'contributors', 'contributor'))
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


def _serialize_people_and_organizations(
    data: dict,
    container: str,
    prefix: str,
    people_and_organizations: list[PersonOrOrganization],
    *,
    record_output=None,
) -> None:
    if not people_and_organizations:
        return
    data[container] = {prefix: []}
    for index, person_or_organization in enumerate(people_and_organizations):
        target = f'{container}[{index}]'
        path = f'/radar:radarDataset/re:{container}/re:{prefix}[{index + 1}]'
        item = {
            f'{prefix}Name': person_or_organization.name,
            'nameType': person_or_organization.name_type,
            'givenName': person_or_organization.given_name,
            'familyName': person_or_organization.family_name,
        }
        for field, name in (('name', f'{prefix}Name'), ('given_name', 'givenName'), ('family_name', 'familyName')):
            record_binding(record_output, f'{target}.{field}', f'{path}/re:{name}', item[name])
        # The XML renderer does not emit nameType.
        if prefix == 'contributor':
            item['contributorType'] = person_or_organization.contributor_type
            record_binding(
                record_output, f'{target}.contributor_type', f'{path}/@contributorType', item['contributorType']
            )
        if person_or_organization.identifiers:
            identifiers = []
            for number, identifier in enumerate(person_or_organization.identifiers):
                identifiers.append({'value': identifier.value, 'nameIdentifierScheme': identifier.identifier_type})
                output_path = f'{path}/re:nameIdentifier[{number + 1}]'
                record_binding(record_output, f'{target}.identifiers[{number}].value', output_path, identifier.value)
                record_binding(
                    record_output,
                    f'{target}.identifiers[{number}].identifier_type',
                    f'{output_path}/@nameIdentifierScheme',
                    identifier.identifier_type,
                )
            item['nameIdentifier'] = identifiers
        if person_or_organization.affiliations:
            item[f'{prefix}Affiliation'] = _serialize_affiliation(
                person_or_organization.affiliations[0],
                target=f'{target}.affiliations[0]',
                path=f'{path}/re:{prefix}Affiliation',
                record_output=record_output,
            )
        data[container][prefix].append(item)


def _serialize_affiliation(affiliation: Affiliation, *, target='', path='', record_output=None) -> str | dict:
    record_binding(record_output, f'{target}.name', path, affiliation.name)
    if not affiliation.identifier:
        return affiliation.name
    data = {
        'value': affiliation.name,
        'affiliationIdentifier': affiliation.identifier,
        'affiliationIdentifierScheme': affiliation.identifier_scheme,
    }
    record_binding(record_output, f'{target}.identifier', f'{path}/@affiliationIdentifier', affiliation.identifier)
    record_binding(
        record_output,
        f'{target}.identifier_scheme',
        f'{path}/@affiliationIdentifierScheme',
        affiliation.identifier_scheme,
    )
    return data


def _serialize_named_value(
    person_or_organization: PersonOrOrganization,
    *,
    target='',
    path='',
    record_output=None,
) -> str | dict:
    record_binding(record_output, f'{target}.name', path, person_or_organization.name)
    if not person_or_organization.identifiers:
        return person_or_organization.name
    identifier = person_or_organization.identifiers[0]
    data = {
        'value': person_or_organization.name,
        'nameIdentifier': identifier.value,
        'nameIdentifierScheme': identifier.identifier_type,
    }
    record_binding(record_output, f'{target}.identifiers[0].value', f'{path}/@nameIdentifier', identifier.value)
    record_binding(
        record_output,
        f'{target}.identifiers[0].identifier_type',
        f'{path}/@nameIdentifierScheme',
        identifier.identifier_type,
    )
    return data


def _serialize_geo_location(location: GeoLocation, *, target='', path='', record_output=None) -> dict:
    data = {
        'geoLocationCountry': location.country,
        'geoLocationRegion': location.region,
        'geoLocationPoint': {
            'latitude': location.latitude,
            'longitude': location.longitude,
        }
        if location.latitude and location.longitude
        else None,
    }
    record_binding(record_output, f'{target}.country', f'{path}/re:geoLocationCountry', location.country)
    record_binding(record_output, f'{target}.region', f'{path}/re:geoLocationRegion', location.region)
    if data['geoLocationPoint'] is not None:
        for field, value in data['geoLocationPoint'].items():
            record_binding(record_output, f'{target}.{field}', f'{path}/re:geoLocationPoint/re:{field}', value)
    return data


def _serialize_software(software: Software, *, target='', path='', record_output=None) -> dict:
    data = {
        'type': software.software_type,
        'softwareName': software.name,
        'softwareVersion': software.version,
        'alternativeSoftwareName': software.alternative_name,
        'alternativeSoftwareVersion': software.alternative_version,
    }
    record_binding(record_output, f'{target}.software_type', f'{path}/@type', software.software_type)
    record_binding(record_output, f'{target}.name', f'{path}/re:softwareName', software.name)
    record_binding(record_output, f'{target}.version', f'{path}/re:softwareName/@softwareVersion', software.version)
    record_binding(
        record_output, f'{target}.alternative_name', f'{path}/re:alternativeSoftwareName', software.alternative_name
    )
    record_binding(
        record_output,
        f'{target}.alternative_version',
        f'{path}/re:alternativeSoftwareName/@alternativeSoftwareVersion',
        software.alternative_version,
    )
    return data


def _serialize_funding(reference: FundingReference, *, target='', path='', record_output=None) -> dict:
    data = {
        'funderName': reference.funder_name,
        'awardNumber': reference.award_number,
        'awardURI': reference.award_uri,
        'awardTitle': reference.award_title,
    }
    for field, name in (
        ('funder_name', 'funderName'),
        ('award_number', 'awardNumber'),
        ('award_uri', 'awardURI'),
        ('award_title', 'awardTitle'),
    ):
        record_binding(record_output, f'{target}.{field}', f'{path}/re:{name}', data[name])
    if reference.funder_identifier:
        identifier = reference.funder_identifier
        data['funderIdentifier'] = {
            'value': identifier.value,
            'type': identifier.identifier_type,
        }
        record_binding(
            record_output, f'{target}.funder_identifier.value', f'{path}/re:funderIdentifier', identifier.value
        )
        record_binding(
            record_output,
            f'{target}.funder_identifier.identifier_type',
            f'{path}/re:funderIdentifier/@type',
            identifier.identifier_type,
        )
    return data


def _parse_people_and_organizations(root: Element, container: str, prefix: str) -> list[PersonOrOrganization]:
    people_and_organizations = []
    for element in _findall(root, container, prefix):
        name = _text(element, f'{prefix}Name')
        if not name:
            continue
        identifiers = [
            Identifier(value.text, value.get('nameIdentifierScheme'))
            for value in element.findall(_q('nameIdentifier'))
            if value.text
        ]
        affiliation = _find(element, f'{prefix}Affiliation')
        affiliations = []
        if affiliation is not None and affiliation.text:
            affiliations.append(
                Affiliation(
                    affiliation.text,
                    affiliation.get('affiliationIdentifier'),
                    affiliation.get('affiliationIdentifierScheme'),
                )
            )
        people_and_organizations.append(
            PersonOrOrganization(
                name=name,
                given_name=_text(element, 'givenName'),
                family_name=_text(element, 'familyName'),
                name_type='Personal' if _text(element, 'givenName') or _text(element, 'familyName') else None,
                identifiers=identifiers,
                affiliations=affiliations,
                contributor_type=element.get('contributorType') if prefix == 'contributor' else None,
            )
        )
    return people_and_organizations


def _parse_named_values(root: Element, container: str, name: str) -> list[PersonOrOrganization]:
    people_and_organizations = []
    for element in _findall(root, container, name):
        if not element.text:
            continue
        identifier = element.get('nameIdentifier')
        people_and_organizations.append(
            PersonOrOrganization(
                name=element.text,
                identifiers=[Identifier(identifier, element.get('nameIdentifierScheme'))] if identifier else [],
            )
        )
    return people_and_organizations


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
        for element in _findall(root, container, name)
        if element.text
    ]


def _parse_geo_locations(root: Element) -> list[GeoLocation]:
    locations = []
    for element in _findall(root, 'geoLocations', 'geoLocation'):
        point = _find(element, 'geoLocationPoint')
        locations.append(
            GeoLocation(
                country=_text(element, 'geoLocationCountry'),
                region=_text(element, 'geoLocationRegion'),
                latitude=_text(point, 'latitude') if point is not None else None,
                longitude=_text(point, 'longitude') if point is not None else None,
            )
        )
    return locations


def _parse_software(root: Element) -> list[Software]:
    software = []
    for element in _findall(root, 'software', 'softwareType'):
        name = _find(element, 'softwareName')
        alternative = _find(element, 'alternativeSoftwareName')
        if name is not None and name.text:
            software.append(
                Software(
                    name.text,
                    element.get('type'),
                    name.get('softwareVersion'),
                    alternative.text if alternative is not None else None,
                    alternative.get('alternativeSoftwareVersion') if alternative is not None else None,
                )
            )
    return software


def _parse_funding(root: Element) -> list[FundingReference]:
    references = []
    for element in _findall(root, 'fundingReferences', 'fundingReference'):
        identifier = _find(element, 'funderIdentifier')
        references.append(
            FundingReference(
                funder_name=_text(element, 'funderName'),
                funder_identifier=Identifier(identifier.text, identifier.get('type'))
                if identifier is not None and identifier.text
                else None,
                award_number=_text(element, 'awardNumber'),
                award_uri=_text(element, 'awardURI'),
                award_title=_text(element, 'awardTitle'),
            )
        )
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
