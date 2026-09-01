import zipfile

from django.http import HttpResponse, HttpResponseBadRequest

from rdmo.core.exports import prettify_xml
from rdmo.projects.exports import Export

from .renderers import RadarExportRenderer
from .validation import validate_radar_xml


class RadarExport(Export):

    other = 'Other'

    abstract = 'Abstract'

    description_type_options = {
        'description_type/abstract': 'Abstract',
        'description_type/object': 'Object',
        'description_type/method': 'Method',
        'description_type/table_of_contents': 'TableOfContents',
        'description_type/technical_info': 'TechnicalInfo',
        'description_type/technical_remarks': 'TechnicalRemarks',
        'description_type/version_notes': 'VersionNotes',
        'description_type/other': 'Other'
    }

    identifier_type_options = {
        'identifier_type/doi': 'DOI',
        'identifier_type/url': 'URL',
        'identifier_type/handle': 'Handle',
        'identifier_type/radar': 'RADAR',
        'identifier_type/other': 'Other'
    }

    primary_identifier_types = {'DOI', 'Handle', 'RADAR'}

    related_identifier_type_options = {
        'identifier_type/ark': 'ARK',
        'identifier_type/arxiv': 'arXiv',
        'identifier_type/bibcode': 'bibcode',
        'identifier_type/cstr': 'CSTR',
        'identifier_type/doi': 'DOI',
        'identifier_type/ean13': 'EAN13',
        'identifier_type/eissn': 'EISSN',
        'identifier_type/handle': 'Handle',
        'identifier_type/epic': 'ePIC',
        'identifier_type/igsn': 'IGSN',
        'identifier_type/isbn': 'ISBN',
        'identifier_type/issn': 'ISSN',
        'identifier_type/istc': 'ISTC',
        'identifier_type/lissn': 'LISSN',
        'identifier_type/lsid': 'LSID',
        'identifier_type/pmid': 'PMID',
        'identifier_type/purl': 'PURL',
        'identifier_type/raid': 'RAiD',
        'identifier_type/rrid': 'RRID',
        'identifier_type/swhid': 'SWHID',
        'identifier_type/upc': 'UPC',
        'identifier_type/url': 'URL',
        'identifier_type/urn': 'URN',
        'identifier_type/w3id': 'w3id'
    }

    language_options = {
        'language/en': 'eng',
        'language/de': 'deu'
    }

    name_type_options = {
        'name_type/personal': 'Personal',
        'name_type/organizational': 'Organizational'
    }

    name_identifier_scheme_options = {
        'name_identifier_scheme/orcid': 'ORCID',
        'name_identifier_scheme/ror': 'ROR',
        'name_identifier_scheme/isni': 'Other',
        'name_identifier_scheme/insi': 'Other',
        'name_identifier_scheme/grid': 'Other',
        'name_identifier_scheme/other': 'Other'
    }

    funder_identifier_scheme_options = {
        'name_identifier_scheme/crossref_funder': 'CrossRefFunder',
        'name_identifier_scheme/grid': 'GRID',
        'name_identifier_scheme/isni': 'ISNI',
        'name_identifier_scheme/insi': 'ISNI',
        'name_identifier_scheme/ror': 'ROR',
        'name_identifier_scheme/other': 'Other'
    }

    contributor_type_options = {
        'contributor_type/contact_person': 'ContactPerson',
        'contributor_type/contact_persion': 'ContactPerson',
        'contributor_type/data_collector': 'DataCollector',
        'contributor_type/data_curator': 'DataCurator',
        'contributor_type/data_manager': 'DataManager',
        'contributor_type/distributor': 'Distributor',
        'contributor_type/editor': 'Editor',
        'contributor_type/hosting_institution': 'HostingInstitution',
        'contributor_type/producer': 'Producer',
        'contributor_type/project_leader': 'ProjectLeader',
        'contributor_type/project_manager': 'ProjectManager',
        'contributor_type/project_member': 'ProjectMember',
        'contributor_type/registration_agency': 'RegistrationAgency',
        'contributor_type/registration_authority': 'RegistrationAuthority',
        'contributor_type/related_person': 'RelatedPerson',
        'contributor_type/researcher': 'Researcher',
        'contributor_type/research_group': 'ResearchGroup',
        'contributor_type/sponsor': 'Sponsor',
        'contributor_type/supervisor': 'Supervisor',
        'contributor_type/translator': 'Translator',
        'contributor_type/work_package_leader': 'WorkPackageLeader',
        'contributor_type/other': 'Other'
    }

    resource_type_general_options = {
        'resource_type_general/audiovisual': 'Audiovisual',
        'resource_type_general/collection': 'Collection',
        'resource_type_general/computational_notebook': 'ComputationalNotebook',
        'resource_type_general/data_paper': 'DataPaper',
        'resource_type_general/dataset': 'Dataset',
        'resource_type_general/event': 'Event',
        'resource_type_general/image': 'Image',
        'resource_type_general/interactive_resource': 'InteractiveResource',
        'resource_type_general/instrument': 'Instrument',
        'resource_type_general/model': 'Model',
        'resource_type_general/physical_object': 'PhysicalObject',
        'resource_type_general/project': 'Project',
        'resource_type_general/service': 'Service',
        'resource_type_general/software': 'Software',
        'resource_type_general/sound': 'Sound',
        'resource_type_general/standard': 'Standard',
        'resource_type_general/text': 'Text',
        'resource_type_general/workflow': 'Workflow',
        'resource_type_general/other': 'Other'
    }

    controlled_subject_area_options = {
        'radar_controlled_subject_area/agriculture': 'Agriculture',
        'radar_controlled_subject_area/architecture': 'Architecture',
        'radar_controlled_subject_area/arts_and_media': 'Arts and Media',
        'radar_controlled_subject_area/astrophysics_and_astronomy': 'Astrophysics and Astronomy',
        'radar_controlled_subject_area/biochemistry': 'Biochemistry',
        'radar_controlled_subject_area/biology': 'Biology',
        'radar_controlled_subject_area/behavioural_sciences': 'Behavioural Sciences',
        'radar_controlled_subject_area/chemistry': 'Chemistry',
        'radar_controlled_subject_area/computer_science': 'Computer Science',
        'radar_controlled_subject_area/economics': 'Economics',
        'radar_controlled_subject_area/engineering': 'Engineering',
        'radar_controlled_subject_area/environmental_science_and_ecology': 'Environmental Science and Ecology',
        'radar_controlled_subject_area/ethnology': 'Ethnology',
        'radar_controlled_subject_area/geological_science': 'Geological Science',
        'radar_controlled_subject_area/geography': 'Geography',
        'radar_controlled_subject_area/history': 'History',
        'radar_controlled_subject_area/horticulture': 'Horticulture',
        'radar_controlled_subject_area/information_technology': 'Information Technology',
        'radar_controlled_subject_area/life_science': 'Life Science',
        'radar_controlled_subject_area/linguistics': 'Linguistics',
        'radar_controlled_subject_area/materials_science': 'Materials Science',
        'radar_controlled_subject_area/mathematics': 'Mathematics',
        'radar_controlled_subject_area/medicine': 'Medicine',
        'radar_controlled_subject_area/philosophy': 'Philosophy',
        'radar_controlled_subject_area/physics': 'Physics',
        'radar_controlled_subject_area/psychology': 'Psychology',
        'radar_controlled_subject_area/social_sciences': 'Social Sciences',
        'radar_controlled_subject_area/software_technology': 'Software Technology',
        'radar_controlled_subject_area/sports': 'Sports',
        'radar_controlled_subject_area/theology': 'Theology',
        'radar_controlled_subject_area/veterinary_medicine': 'Veterinary Medicine',
        'radar_controlled_subject_area/other': 'Other'
    }

    data_source_options = {
        'radar_data_source/instrument': 'Instrument',
        'radar_data_source/media': 'Media',
        'radar_data_source/observation': 'Observation',
        'radar_data_source/survey': 'Survey',
        'radar_data_source/trial': 'Trial',
        'radar_data_source/organism': 'Organism',
        'radar_data_source/tissue': 'Tissue',
        'radar_data_source/other': 'Other'
    }

    software_type_options = {
        'radar_software_type/resource_production': 'Resource Production',
        'radar_software_type/resource_processing': 'Resource Processing',
        'radar_software_type/resource_viewing': 'Resource Viewing',
        'radar_software_type/other': 'Other'
    }

    controlled_rights_options = {
        'dataset_license_types/71': 'CC BY 4.0 Attribution',
        'dataset_license_types/74': 'CC BY-ND 4.0 Attribution-NoDerivs',
        'dataset_license_types/75': 'CC BY-SA 4.0 Attribution-ShareAlike',
        'dataset_license_types/73': 'CC BY-NC 4.0 Attribution-NonCommercial',
        'dataset_license_types/cc0': 'CC0 1.0 Universal Public Domain Dedication',
        'dataset_license_types/233': 'Other'
    }

    relation_type_options = {
        'relation_type/is_cited_by': 'IsCitedBy',
        'relation_type/cites': 'Cites',
        'relation_type/is_supplement_to': 'IsSupplementTo',
        'relation_type/is_supplemented_by': 'IsSupplementedBy',
        'relation_type/is_continued_by': 'IsContinuedBy',
        'relation_type/continues': 'Continues',
        'relation_type/describes': 'Describes',
        'relation_type/is_described_by': 'IsDescribedBy',
        'relation_type/has_metadata': 'HasMetadata',
        'relation_type/is_metadata_for': 'IsMetadataFor',
        'relation_type/has_version': 'HasVersion',
        'relation_type/is_version_of': 'IsVersionOf',
        'relation_type/is_new_version_of': 'IsNewVersionOf',
        'relation_type/is_previous_version_of': 'IsPreviousVersionOf',
        'relation_type/is_part_of': 'IsPartOf',
        'relation_type/has_part': 'HasPart',
        'relation_type/is_published_in': 'IsPublishedIn',
        'relation_type/is_referenced_by': 'IsReferencedBy',
        'relation_type/references': 'References',
        'relation_type/is_documented_by': 'IsDocumentedBy',
        'relation_type/documents': 'Documents',
        'relation_type/is_compiled_by': 'IsCompiledBy',
        'relation_type/compiles': 'Compiles',
        'relation_type/Compiles': 'Compiles',
        'relation_type/is_variant_form_of': 'IsVariantFormOf',
        'relation_type/is_original_form_of': 'IsOriginalFormOf',
        'relation_type/is_identical_to': 'IsIdenticalTo',
        'relation_type/is_reviewed_by': 'IsReviewedBy',
        'relation_type/reviews': 'Reviews',
        'relation_type/is_derived_from': 'IsDerivedFrom',
        'relation_type/is_source_of': 'IsSourceOf',
        'relation_type/requires': 'Requires',
        'relation_type/is_required_by': 'IsRequiredBy',
        'relation_type/obsoletes': 'Obsoletes',
        'relation_type/is_obsoleted_by': 'IsObsoletedBy',
        'relation_type/is_collected_by': 'IsCollectedBy',
        'relation_type/collects': 'Collects',
        'relation_type/has_translation': 'HasTranslation',
        'relation_type/is_translation_of': 'IsTranslationOf'
    }

    def get_dataset(self, set_index):
        dataset = {}

        # identifier
        identifier = self.get_text('project/dataset/identifier', set_index=set_index)
        if identifier:
            identifier_type = \
                self.get_option(self.identifier_type_options, 'project/dataset/identifier_type',
                                set_index=set_index) or \
                self.get_option(self.identifier_type_options, 'project/dataset/pids/system',
                                set_index=set_index)
            if identifier_type in self.primary_identifier_types:
                dataset['identifier'] = identifier
                dataset['identifierType'] = identifier_type

        # creators
        for creator_set in self.get_set('project/dataset/creator/name', set_prefix=str(set_index)):
            creator = self.get_name('creator', 'project/dataset/creator',
                                    set_prefix=creator_set.set_prefix, set_index=creator_set.set_index)
            if creator:
                if 'creators' not in dataset:
                    dataset['creators'] = {
                        'creator': []
                    }
                dataset['creators']['creator'].append(creator)

        # title
        dataset['title'] =  \
            self.get_text('project/dataset/title', set_index=set_index) or \
            self.get_text('project/dataset/id', set_index=set_index) or \
            f'Dataset #{set_index + 1}'

        # publisher
        publisher = \
            self.get_text('project/dataset/publisher', set_index=set_index) or \
            self.get_text('project/dataset/preservation/repository', set_index=set_index)
        if publisher:
            dataset['publishers'] = {
                'publisher': [publisher]
            }

        # productionYear
        production_year = \
            self.get_year('project/dataset/created', set_index=set_index) or \
            self.get_year('project/dataset/data_publication_date', set_index=set_index)
        if production_year:
            dataset['productionYear'] = production_year

        # publicationYear
        publication_year = \
            self.get_year('project/dataset/issued', set_index=set_index) or \
            self.get_year('project/dataset/data_publication_date', set_index=set_index)
        if publication_year:
            dataset['publicationYear'] = publication_year

        # subjectArea
        subject_areas = \
            self.get_values('project/dataset/subject', set_index=set_index) or \
            self.get_values('project/research_field/title')

        if subject_areas:
            dataset['subjectAreas'] = {
                'subjectArea': []
            }
            for subject_area in subject_areas:
                if subject_area.is_true:
                    if subject_area.option:
                        controlled_subject_area_name = \
                            self.controlled_subject_area_options.get(subject_area.option.uri_path, self.other)
                    else:
                        controlled_subject_area_name = self.other

                    if controlled_subject_area_name == self.other:
                        dataset['subjectAreas']['subjectArea'].append({
                            'controlledSubjectAreaName': controlled_subject_area_name,
                            'additionalSubjectAreaName': subject_area.value
                        })
                    else:
                        dataset['subjectAreas']['subjectArea'].append({
                            'controlledSubjectAreaName': controlled_subject_area_name
                        })

        # resource
        resource_type = self.get_text('project/dataset/resource_type', set_index=set_index)
        if resource_type:
            dataset['resource'] = {
                'value': resource_type,
                'resourceType': self.get_option(self.resource_type_general_options,
                                                'project/dataset/resource_type_general', set_index=set_index)
            }

        dataset['title'] = \
            self.get_text('project/dataset/title', set_index=set_index) or \
            self.get_text('project/dataset/id', set_index=set_index) or \
            f'Dataset #{set_index + 1}'

        # alternate_identifiers
        alternate_identifier_sets = self.get_set('project/dataset/alternate_identifier/identifier',
                                                 set_prefix=str(set_index))
        if alternate_identifier_sets:
            dataset['alternateIdentifiers'] = {
              'alternateIdentifier': []
            }
            for alternate_identifier_set in alternate_identifier_sets:
                dataset['alternateIdentifiers']['alternateIdentifier'].append({
                    'value': self.get_text('project/dataset/alternate_identifier/identifier',
                                           set_prefix=alternate_identifier_set.set_prefix,
                                           set_index=alternate_identifier_set.set_index),
                    'alternateIdentifierType': self.get_option(self.identifier_type_options,
                                                               'project/dataset/alternate_identifier/identifier_type',
                                                               set_prefix=alternate_identifier_set.set_prefix,
                                                               set_index=alternate_identifier_set.set_index)
                })

        # related_identifiers
        related_identifier_sets = self.get_set('project/dataset/related_identifier/identifier',
                                               set_prefix=str(set_index))
        if related_identifier_sets:
            dataset['relatedIdentifiers'] = {
              'relatedIdentifier': []
            }
            for related_identifier_set in related_identifier_sets:
                dataset['relatedIdentifiers']['relatedIdentifier'].append({
                    'value': self.get_text('project/dataset/related_identifier/identifier',
                                           set_prefix=related_identifier_set.set_prefix,
                                           set_index=related_identifier_set.set_index),
                    'relatedIdentifierType': self.get_option(self.related_identifier_type_options,
                                                             'project/dataset/related_identifier/identifier_type',
                                                             set_prefix=related_identifier_set.set_prefix,
                                                             set_index=related_identifier_set.set_index),
                    'relationType': self.get_option(self.relation_type_options,
                                                    'project/dataset/related_identifier/relation_type',
                                                    set_prefix=related_identifier_set.set_prefix,
                                                    set_index=related_identifier_set.set_index)
                })

        # rights
        rights_list = self.get_values('project/dataset/sharing/conditions', set_index=set_index)
        if rights_list:
            dataset['rights'] = []
            for rights in rights_list:
                if rights.option:
                    controlled_rights = self.controlled_rights_options.get(rights.option.uri_path, self.other)
                else:
                    controlled_rights = self.other

                dataset['rights'] = {
                    'controlledRights': controlled_rights,
                    'additionalRights': rights.value if controlled_rights == self.other else None
                }

        # rights holders
        rights_holders = self.get_list('project/dataset/sharing/rights_holder', set_index=set_index)
        if rights_holders:
            dataset['rightsHolders'] = {
                'rightsHolder': rights_holders
            }

        # description
        description = self.get_text('project/dataset/description', set_index=set_index)
        if description:
            dataset['descriptions'] = {
                'description': [{
                    'value': description,
                    'descriptionType': self.abstract
                }]
            }

        # keywords
        keywords = self.get_list('project/research_question/keywords')
        if keywords:
            dataset['keywords'] = {
                'keyword': [{'value': keyword} for keyword in keywords]
            }

        # contributors
        for contributor_set in self.get_set('project/dataset/contributor/name', set_prefix=str(set_index)):
            contributor = self.get_name('contributor', 'project/dataset/contributor',
                                        set_prefix=contributor_set.set_prefix, set_index=contributor_set.set_index)

            if contributor:
                if 'contributors' not in dataset:
                    dataset['contributors'] = {
                        'contributor': []
                    }
                dataset['contributors']['contributor'].append(contributor)

        # language
        language = self.get_option(self.language_options, 'project/dataset/language', set_index=set_index)
        if language:
            dataset['language'] = language

        # dataSource
        data_source = self.get_text('project/dataset/data_source', set_index=set_index)
        if data_source:
            dataset['dataSources'] = {
                'dataSource': [{
                    'value': data_source,
                    'dataSourceDetail': self.get_option(self.data_source_options, 'project/dataset/data_source_detail',
                                                        set_index=set_index)
                }]
            }

        # dataProcessing
        # data_processing = self.get_list('project/dataset/data_processing', set_index=set_index)
        # if data_processing:
        #     dataset['dataProcessing'] = data_processing

        # funding_references
        funding_reference_sets = self.get_set('project/funder/id')
        if funding_reference_sets:
            dataset['fundingReferences'] = {
                'fundingReference': []
            }
            for funding_reference_set in funding_reference_sets:
                funding_reference = {
                    'funderName': self.get_text(
                        'project/funder/name',
                        set_index=funding_reference_set.set_index
                    ),
                    'awardURI': self.get_text(
                        'project/funder/programme/url',
                        set_index=funding_reference_set.set_index
                    ),
                    'awardNumber': self.get_text(
                        'project/funder/programme/number',
                        set_index=funding_reference_set.set_index
                    ),
                    'awardTitle': self.get_text(
                        'project/funder/programme/title',
                        set_index=funding_reference_set.set_index
                    )
                }

                funder_identifier = self.get_text('project/funder/name_identifier',
                                                  set_index=funding_reference_set.set_index)
                if funder_identifier:
                    funding_reference['funderIdentifier'] = {
                        'value': funder_identifier,
                        'type': self.get_option(
                            self.funder_identifier_scheme_options,
                            'project/funder/name_identifier_scheme',
                            set_index=funding_reference_set.set_index,
                            default=self.other
                        )
                    }

                dataset['fundingReferences']['fundingReference'].append(funding_reference)

        version = self.get_text('project/dataset/version', set_index=set_index)
        if version:
            dataset['version'] = version

        return dataset

    def get_name(self, prefix, attribute, set_prefix='', set_index=0):
        name_text = self.get_text(attribute + '/name', set_prefix=set_prefix, set_index=set_index)
        if name_text:
            name = {
                'nameType': self.get_option(self.name_type_options, attribute + '/name_type',
                                            set_prefix=set_prefix, set_index=set_index, default='Personal'),
            }

            if prefix == 'contributor':
                contributor_type = self.get_option(self.contributor_type_options, attribute + '/contributor_type',
                                                   set_prefix=set_prefix, set_index=set_index, default=self.other)
                if contributor_type:
                    name['contributorType'] = contributor_type

            # given_name
            given_name = self.get_text(attribute + '/given_name', set_prefix=set_prefix, set_index=set_index)
            if given_name:
                name['givenName'] = given_name

            # family_name
            family_name = self.get_text(attribute + '/family_name', set_prefix=set_prefix, set_index=set_index)
            if family_name:
                name['familyName'] = family_name

            name[f'{prefix}Name'] = name_text

            # identifier
            identifier = self.get_text(attribute + '/name_identifier', set_prefix=set_prefix, set_index=set_index)
            if identifier:
                name['nameIdentifier'] = [{
                    'value': identifier,
                    'nameIdentifierScheme': self.get_option(self.name_identifier_scheme_options,
                                                            attribute + '/name_identifier_scheme',
                                                            set_prefix=set_prefix, set_index=set_index,
                                                            default=self.other)
                }]

            # affiliations
            affiliations = self.get_list(attribute + '/affiliation', set_prefix=set_prefix, set_index=set_index)
            if affiliations:
                name[f'{prefix}Affiliation'] = affiliations[0]

            return name
        else:
            return None

    def render(self):
        files = []
        for rdmo_dataset in self.get_set('project/dataset/id'):
            set_index = rdmo_dataset.set_index

            file_name = '{}.xml'.format(
                self.get_text('project/dataset/identifier', set_index=set_index) or
                self.get_text('project/dataset/id', set_index=set_index) or
                str(set_index + 1)
            )

            dataset = self.get_dataset(set_index)
            xmldata = prettify_xml(RadarExportRenderer().render(dataset))
            validation_error = validate_radar_xml(xmldata)
            if validation_error:
                return HttpResponseBadRequest(
                    f'RADAR XML validation failed for "{file_name}": {validation_error}',
                    content_type='text/plain'
                )
            files.append((file_name, xmldata))

        response = HttpResponse(content_type='application/zip')
        response['Content-Disposition'] = f'filename="{self.project.title}.zip"'
        with zipfile.ZipFile(response, 'w') as zip_file:
            for file_name, xmldata in files:
                zip_file.writestr(file_name, xmldata)

        return response
