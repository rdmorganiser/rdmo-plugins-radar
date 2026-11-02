"""Template Framework views of the shared RADAR vocabularies."""

from ...metadata.constants import to_api_value
from ..common import vocabulary as common_options

LANGUAGE_OPTIONS = dict(common_options.LANGUAGE_OPTIONS)


class XMLVocabulary:
    other = common_options.OTHER
    abstract = common_options.ABSTRACT
    description_type_options = dict(common_options.DESCRIPTION_TYPE_OPTIONS)
    identifier_type_options = dict(common_options.IDENTIFIER_TYPE_OPTIONS)
    primary_identifier_types = set(common_options.PRIMARY_IDENTIFIER_TYPES)
    related_identifier_type_options = dict(common_options.RELATED_IDENTIFIER_TYPE_OPTIONS)
    language_options = LANGUAGE_OPTIONS
    name_type_options = dict(common_options.NAME_TYPE_OPTIONS)
    name_identifier_scheme_options = dict(common_options.NAME_IDENTIFIER_SCHEME_OPTIONS)
    funder_identifier_scheme_options = dict(common_options.FUNDER_IDENTIFIER_SCHEME_OPTIONS)
    contributor_type_options = dict(common_options.CONTRIBUTOR_TYPE_OPTIONS)
    resource_type_general_options = dict(common_options.RESOURCE_TYPE_GENERAL_OPTIONS)
    controlled_subject_area_options = dict(common_options.CONTROLLED_SUBJECT_AREA_OPTIONS)
    data_source_options = dict(common_options.DATA_SOURCE_OPTIONS)
    software_type_options = dict(common_options.SOFTWARE_TYPE_OPTIONS)
    controlled_rights_options = dict(common_options.CONTROLLED_RIGHTS_OPTIONS)
    relation_type_options = dict(common_options.RELATION_TYPE_OPTIONS)


def _api_options(options):
    return {key: to_api_value(value) for key, value in options.items()}


class APIVocabulary:
    other = to_api_value(XMLVocabulary.other)
    abstract = to_api_value(XMLVocabulary.abstract)
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
