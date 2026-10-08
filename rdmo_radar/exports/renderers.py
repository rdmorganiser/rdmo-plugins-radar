from rdmo.core.renderers import BaseXMLRenderer


class RadarExportRenderer(BaseXMLRenderer):

    scheme_uri = {
        'ORCID': 'https://orcid.org/',
        'ROR': 'https://ror.org/'
    }

    def render_document(self, xml, dataset):
        xml.startElement('radar:radarDataset', {
            'xmlns:radar': 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-dataset',
            'xmlns:re': 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'
        })

        self.render_identifier(xml, dataset)
        self.render_alternate_identifiers(xml, dataset)
        self.render_related_identifiers(xml, dataset)
        self.render_names(xml, dataset, 'creators', 'creator')
        self.render_names(xml, dataset, 'contributors', 'contributor')
        self.render_optional_text(xml, 'title', dataset.get('title'))
        self.render_additional_titles(xml, dataset)
        self.render_descriptions(xml, dataset)
        self.render_keywords(xml, dataset)
        self.render_publishers(xml, dataset)
        self.render_optional_text(xml, 'productionYear', dataset.get('productionYear'))
        self.render_optional_text(xml, 'publicationYear', dataset.get('publicationYear'))
        self.render_optional_text(xml, 'language', dataset.get('language'))
        self.render_subject_areas(xml, dataset)
        self.render_resource(xml, dataset)
        self.render_geo_locations(xml, dataset)
        self.render_data_sources(xml, dataset)
        self.render_software(xml, dataset)
        self.render_processing(xml, dataset)
        self.render_rights(xml, dataset)
        self.render_rights_holders(xml, dataset)
        self.render_related_informations(xml, dataset)
        self.render_funding_references(xml, dataset)
        self.render_optional_text(xml, 'version', dataset.get('version'))

        xml.endElement('radar:radarDataset')

    def render_optional_text(self, xml, tag, value, attrs=None):
        if value not in (None, ''):
            self.render_text_element(
                xml,
                f're:{tag}',
                {key: item for key, item in (attrs or {}).items() if item not in (None, '')},
                value
            )

    def render_identifier(self, xml, dataset):
        if dataset.get('identifier') is not None:
            self.render_optional_text(xml, 'identifier', dataset.get('identifier'), {
                'identifierType': dataset.get('identifierType')
            })

    def render_alternate_identifiers(self, xml, dataset):
        identifiers = dataset.get('alternateIdentifiers', {}).get('alternateIdentifier')
        if identifiers:
            xml.startElement('re:alternateIdentifiers', {})
            for identifier in identifiers:
                self.render_optional_text(xml, 'alternateIdentifier', identifier.get('value'), {
                    'alternateIdentifierType': identifier.get('alternateIdentifierType')
                })
            xml.endElement('re:alternateIdentifiers')

    def render_related_identifiers(self, xml, dataset):
        identifiers = dataset.get('relatedIdentifiers', {}).get('relatedIdentifier')
        if identifiers:
            xml.startElement('re:relatedIdentifiers', {})
            for identifier in identifiers:
                self.render_optional_text(xml, 'relatedIdentifier', identifier.get('value'), {
                    'relatedIdentifierType': identifier.get('relatedIdentifierType'),
                    'relationType': identifier.get('relationType')
                })
            xml.endElement('re:relatedIdentifiers')

    def render_names(self, xml, dataset, container, prefix):
        names = dataset.get(container, {}).get(prefix)
        if not names:
            return

        xml.startElement(f're:{container}', {})
        for name in names:
            attrs = {'contributorType': name.get('contributorType')} if prefix == 'contributor' else {}
            xml.startElement(f're:{prefix}', {key: value for key, value in attrs.items() if value})
            self.render_optional_text(xml, f'{prefix}Name', name.get(f'{prefix}Name'))
            self.render_optional_text(xml, 'givenName', name.get('givenName'))
            self.render_optional_text(xml, 'familyName', name.get('familyName'))

            for identifier in name.get('nameIdentifier') or []:
                scheme = identifier.get('nameIdentifierScheme')
                self.render_optional_text(xml, 'nameIdentifier', identifier.get('value'), {
                    'nameIdentifierScheme': scheme,
                    'schemeURI': self.scheme_uri.get(scheme)
                })

            affiliation = name.get(f'{prefix}Affiliation')
            if isinstance(affiliation, dict):
                self.render_optional_text(xml, f'{prefix}Affiliation', affiliation.get('value'), {
                    'affiliationIdentifier': affiliation.get('affiliationIdentifier'),
                    'affiliationIdentifierScheme': affiliation.get('affiliationIdentifierScheme'),
                    'schemeURI': self.scheme_uri.get(affiliation.get('affiliationIdentifierScheme'))
                })
            else:
                self.render_optional_text(xml, f'{prefix}Affiliation', affiliation)
            xml.endElement(f're:{prefix}')
        xml.endElement(f're:{container}')

    def render_additional_titles(self, xml, dataset):
        titles = dataset.get('additionalTitles')
        if titles:
            xml.startElement('re:additionalTitles', {})
            for title in titles:
                self.render_optional_text(xml, 'additionalTitle', title.get('additionalTitle'), {
                    'additionalTitleType': title.get('additionalTitleType')
                })
            xml.endElement('re:additionalTitles')

    def render_descriptions(self, xml, dataset):
        descriptions = dataset.get('descriptions', {}).get('description')
        if descriptions:
            xml.startElement('re:descriptions', {})
            for description in descriptions:
                self.render_optional_text(xml, 'description', description.get('value'), {
                    'descriptionType': description.get('descriptionType')
                })
            xml.endElement('re:descriptions')

    def render_keywords(self, xml, dataset):
        keywords = dataset.get('keywords', {}).get('keyword')
        if keywords:
            xml.startElement('re:keywords', {})
            for keyword in keywords:
                self.render_optional_text(xml, 'keyword', keyword.get('value'))
            xml.endElement('re:keywords')

    def render_publishers(self, xml, dataset):
        publishers = dataset.get('publishers', {}).get('publisher')
        if publishers:
            xml.startElement('re:publishers', {})
            for publisher in publishers:
                if isinstance(publisher, dict):
                    self.render_optional_text(xml, 'publisher', publisher.get('value'), {
                        'nameIdentifierScheme': publisher.get('nameIdentifierScheme'),
                        'schemeURI': publisher.get('schemeURI'),
                        'nameIdentifier': publisher.get('nameIdentifier')
                    })
                else:
                    self.render_optional_text(xml, 'publisher', publisher)
            xml.endElement('re:publishers')

    def render_subject_areas(self, xml, dataset):
        subject_areas = dataset.get('subjectAreas', {}).get('subjectArea')
        if subject_areas:
            xml.startElement('re:subjectAreas', {})
            for subject_area in subject_areas:
                xml.startElement('re:subjectArea', {})
                self.render_optional_text(
                    xml, 'controlledSubjectAreaName', subject_area.get('controlledSubjectAreaName')
                )
                self.render_optional_text(
                    xml, 'additionalSubjectAreaName', subject_area.get('additionalSubjectAreaName')
                )
                xml.endElement('re:subjectArea')
            xml.endElement('re:subjectAreas')

    def render_resource(self, xml, dataset):
        resource = dataset.get('resource')
        if resource:
            self.render_optional_text(xml, 'resource', resource.get('value'), {
                'resourceType': resource.get('resourceType')
            })

    def render_geo_locations(self, xml, dataset):
        locations = dataset.get('geoLocations', {}).get('geoLocation')
        if locations:
            xml.startElement('re:geoLocations', {})
            for location in locations:
                xml.startElement('re:geoLocation', {})
                self.render_optional_text(xml, 'geoLocationCountry', location.get('geoLocationCountry'))
                self.render_optional_text(xml, 'geoLocationRegion', location.get('geoLocationRegion'))
                point = location.get('geoLocationPoint')
                if point:
                    xml.startElement('re:geoLocationPoint', {})
                    self.render_optional_text(xml, 'latitude', point.get('latitude'))
                    self.render_optional_text(xml, 'longitude', point.get('longitude'))
                    xml.endElement('re:geoLocationPoint')
                xml.endElement('re:geoLocation')
            xml.endElement('re:geoLocations')

    def render_data_sources(self, xml, dataset):
        data_sources = dataset.get('dataSources', {}).get('dataSource')
        if data_sources:
            xml.startElement('re:dataSources', {})
            for data_source in data_sources:
                self.render_optional_text(xml, 'dataSource', data_source.get('value'), {
                    'dataSourceDetail': data_source.get('dataSourceDetail')
                })
            xml.endElement('re:dataSources')

    def render_software(self, xml, dataset):
        software = dataset.get('software')
        if software:
            xml.startElement('re:software', {})
            for software_type in software:
                attrs = {'type': software_type.get('type')}
                xml.startElement('re:softwareType', {key: value for key, value in attrs.items() if value})
                self.render_optional_text(xml, 'softwareName', software_type.get('softwareName'), {
                    'softwareVersion': software_type.get('softwareVersion')
                })
                self.render_optional_text(
                    xml,
                    'alternativeSoftwareName',
                    software_type.get('alternativeSoftwareName'),
                    {'alternativeSoftwareVersion': software_type.get('alternativeSoftwareVersion')}
                )
                xml.endElement('re:softwareType')
            xml.endElement('re:software')

    def render_processing(self, xml, dataset):
        processing_list = dataset.get('dataProcessing')
        if processing_list:
            xml.startElement('re:processing', {})
            for processing in processing_list:
                self.render_optional_text(xml, 'dataProcessing', processing)
            xml.endElement('re:processing')

    def render_rights(self, xml, dataset):
        rights = dataset.get('rights')
        if rights:
            xml.startElement('re:rights', {})
            self.render_optional_text(xml, 'controlledRights', rights.get('controlledRights'))
            self.render_optional_text(xml, 'additionalRights', rights.get('additionalRights'))
            xml.endElement('re:rights')

    def render_rights_holders(self, xml, dataset):
        rights_holders = dataset.get('rightsHolders', {}).get('rightsHolder')
        if rights_holders:
            xml.startElement('re:rightsHolders', {})
            for rights_holder in rights_holders:
                if isinstance(rights_holder, dict):
                    self.render_optional_text(xml, 'rightsHolder', rights_holder.get('value'), {
                        'nameIdentifierScheme': rights_holder.get('nameIdentifierScheme'),
                        'schemeURI': rights_holder.get('schemeURI'),
                        'nameIdentifier': rights_holder.get('nameIdentifier')
                    })
                else:
                    self.render_optional_text(xml, 'rightsHolder', rights_holder)
            xml.endElement('re:rightsHolders')

    def render_related_informations(self, xml, dataset):
        related_informations = dataset.get('relatedInformations')
        if related_informations:
            xml.startElement('re:relatedInformations', {})
            for related_information in related_informations:
                self.render_optional_text(xml, 'relatedInformation', related_information.get('relatedInformation'), {
                    'relatedInformationType': related_information.get('relatedInformationType')
                })
            xml.endElement('re:relatedInformations')

    def render_funding_references(self, xml, dataset):
        references = dataset.get('fundingReferences', {}).get('fundingReference')
        if references:
            xml.startElement('re:fundingReferences', {})
            for reference in references:
                xml.startElement('re:fundingReference', {})
                self.render_optional_text(xml, 'funderName', reference.get('funderName'))
                identifier = reference.get('funderIdentifier')
                if identifier:
                    self.render_optional_text(xml, 'funderIdentifier', identifier.get('value'), {
                        'type': identifier.get('type')
                    })
                self.render_optional_text(xml, 'awardNumber', reference.get('awardNumber'))
                self.render_optional_text(xml, 'awardURI', reference.get('awardURI'))
                self.render_optional_text(xml, 'awardTitle', reference.get('awardTitle'))
                xml.endElement('re:fundingReference')
            xml.endElement('re:fundingReferences')
