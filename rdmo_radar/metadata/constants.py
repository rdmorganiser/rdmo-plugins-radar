import re


class XMLVocabulary:
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


_API_OVERRIDES = {
    'arXiv': 'ARXIV',
    'bibcode': 'BIBCODE',
    'Handle': 'HANDLE',
    'ePIC': 'EPIC',
    'RAiD': 'RAID',
    'w3id': 'W3ID',
    'Personal': 'Personal',
    'Organizational': 'Organizational',
    'CC BY 4.0 Attribution': 'CC_BY_4_0_ATTRIBUTION',
    'CC BY-ND 4.0 Attribution-NoDerivs': 'CC_BY_ND_4_0_ATTRIBUTION_NO_DERIVS',
    'CC BY-SA 4.0 Attribution-ShareAlike': 'CC_BY_SA_4_0_ATTRIBUTION_SHARE_ALIKE',
    'CC BY-NC 4.0 Attribution-NonCommercial': 'CC_BY_NC_4_0_ATTRIBUTION_NON_COMMERCIAL',
    'CC0 1.0 Universal Public Domain Dedication': 'CC_0_1_0_UNIVERSAL_PUBLIC_DOMAIN_DEDICATION',
}


def to_api_value(value: str | None) -> str | None:
    if value is None:
        return None
    if value in _API_OVERRIDES:
        return _API_OVERRIDES[value]
    value = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', value)
    value = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', value)
    return re.sub(r'[^A-Za-z0-9]+', '_', value).strip('_').upper()


def _api_options(options: dict[str, str]) -> dict[str, str]:
    return {key: to_api_value(value) for key, value in options.items()}


class APIVocabulary:
    other = 'OTHER'
    abstract = 'ABSTRACT'
    description_type_options = _api_options(XMLVocabulary.description_type_options)
    identifier_type_options = _api_options(XMLVocabulary.identifier_type_options)
    primary_identifier_types = {to_api_value(value) for value in XMLVocabulary.primary_identifier_types}
    related_identifier_type_options = _api_options(XMLVocabulary.related_identifier_type_options)
    language_options = _api_options(XMLVocabulary.language_options)
    name_type_options = _api_options(XMLVocabulary.name_type_options)
    name_identifier_scheme_options = _api_options(XMLVocabulary.name_identifier_scheme_options)
    funder_identifier_scheme_options = _api_options(XMLVocabulary.funder_identifier_scheme_options)
    contributor_type_options = _api_options(XMLVocabulary.contributor_type_options)
    resource_type_general_options = _api_options(XMLVocabulary.resource_type_general_options)
    controlled_subject_area_options = _api_options(XMLVocabulary.controlled_subject_area_options)
    data_source_options = _api_options(XMLVocabulary.data_source_options)
    software_type_options = _api_options(XMLVocabulary.software_type_options)
    controlled_rights_options = _api_options(XMLVocabulary.controlled_rights_options)
    relation_type_options = _api_options(XMLVocabulary.relation_type_options)
