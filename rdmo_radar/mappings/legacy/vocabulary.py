"""Shared RADAR vocabularies with historical name-identifier interpretations."""

from ..common import vocabulary as common_options

IDENTIFIER_TYPE_OPTIONS = dict(common_options.IDENTIFIER_TYPE_OPTIONS)
RELATED_IDENTIFIER_TYPE_OPTIONS = dict(common_options.RELATED_IDENTIFIER_TYPE_OPTIONS)
LANGUAGE_OPTIONS = dict(common_options.LANGUAGE_OPTIONS)
NAME_TYPE_OPTIONS = dict(common_options.NAME_TYPE_OPTIONS)
CONTRIBUTOR_TYPE_OPTIONS = dict(common_options.CONTRIBUTOR_TYPE_OPTIONS)
RESOURCE_TYPE_OPTIONS = dict(common_options.RESOURCE_TYPE_GENERAL_OPTIONS)
CONTROLLED_SUBJECT_AREA_OPTIONS = dict(common_options.CONTROLLED_SUBJECT_AREA_OPTIONS)
DATA_SOURCE_OPTIONS = dict(common_options.DATA_SOURCE_OPTIONS)
CONTROLLED_RIGHTS_OPTIONS = dict(common_options.CONTROLLED_RIGHTS_OPTIONS)
RELATION_TYPE_OPTIONS = dict(common_options.RELATION_TYPE_OPTIONS)


# Keep the historical interpretations for these two Option paths.
NAME_IDENTIFIER_SCHEME_OPTIONS = {
    **common_options.NAME_IDENTIFIER_SCHEME_OPTIONS,
    'name_identifier_scheme/insi': 'ISNI',
    'name_identifier_scheme/grid': 'GRID',
}
