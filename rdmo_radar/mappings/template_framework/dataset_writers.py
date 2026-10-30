"""Explicit per-field Template Framework import destinations and loss warnings."""

from ...metadata.fields.contracts import Coordinates
from ...metadata.types import GeoLocation, SubjectArea, as_keyword
from ...metadata.values import get_option_path, model_key, normalize
from ...metadata.write_context import ProjectWriteContext
from .vocabulary import XMLVocabulary

RIGHTS_HOLDER_PATH = 'project/dataset/ipr/rightsholder'
LANGUAGE_PATH = 'project/dataset/language'


def write_title(context, value, *, target):
    context.add('project/dataset/title', value)


def write_identifier(context, value, *, target):
    if value:
        context.add('project/dataset/data_publication_pid', value.value)
        context.add_option(
            'project/dataset/pids/system',
            value.identifier_type,
            XMLVocabulary.identifier_type_options,
        )


def write_additional_titles(context, value, *, target):
    _merge_acronym(context, value)


def write_keywords(context, value, *, target):
    for keyword in value:
        term = as_keyword(keyword)
        context.add_unique_text('project/research_question/keywords', term.value, coordinates=Coordinates())
        if term.has_vocabulary_metadata:
            context.warn('keywords', 'Only keyword labels have an established RDMO import destination', term.value)


def write_subject_areas(context, value, *, target):
    _merge_subjects(context, value)


def write_language(context, value, *, target):
    context.add_option(LANGUAGE_PATH, value, XMLVocabulary.language_options)


def write_resource(context, value, *, target):
    if value:
        context.add('project/dataset/description', value.value)
        if value.resource_type:
            context.warn('resource.resourceType', 'No confirmed RDMO resource type mapping', value.resource_type)


def write_rights(context, value, *, target):
    if value:
        context.add_option(
            'project/dataset/sharing/conditions',
            value.controlled,
            XMLVocabulary.controlled_rights_options,
            text=value.additional,
        )


def write_rights_holders(context, value, *, target):
    for collection_index, holder in enumerate(value):
        context.add(RIGHTS_HOLDER_PATH, holder.name, collection_index=collection_index)
        if holder.identifiers:
            context.warn(
                'rightsHolders', 'Only rights-holder names have an established RDMO import destination', holder.name
            )


def write_data_sources(context, value, *, target):
    for collection_index, source in enumerate(value):
        if source.resource_type:
            context.add_option(
                'project/dataset/creation_methods',
                source.resource_type,
                XMLVocabulary.data_source_options,
                text=source.value,
                collection_index=collection_index,
            )
        else:
            context.add('project/dataset/creation_methods', source.value, collection_index=collection_index)


def write_processing(context, value, *, target):
    for collection_index, processing in enumerate(value):
        context.add('project/dataset/method', processing, collection_index=collection_index)


def write_geo_locations(context, value, *, target):
    _write_geo_location(context, value)


def _merge_acronym(context: ProjectWriteContext, titles: list[str]) -> None:
    if not titles:
        return
    acronym = titles[0]
    existing = context.get_values('project/acronym')
    if not existing:
        context.add('project/acronym', acronym, set_index=0, set_prefix='')
    elif all(normalize(value.text) != normalize(acronym) for value in existing):
        context.warn('project/acronym', 'Existing project acronym was preserved', acronym)
    if len(titles) > 1:
        context.warn('additionalTitles', 'Only one project acronym can be mapped')


def _merge_subjects(context: ProjectWriteContext, subjects: list[SubjectArea]) -> None:
    existing_options = {
        model_key(value.option, value.option.uri_path)
        for value in context.get_values('project/research_field/title')
        if value.option
    }
    for subject in subjects:
        option_path = get_option_path(XMLVocabulary.controlled_subject_area_options, subject.controlled_name)
        option = context.fetch_option(option_path) if option_path is not None else None
        if option is not None and model_key(option, option.uri_path) in existing_options:
            continue
        value = context.add_option(
            'project/research_field/title',
            subject.controlled_name,
            XMLVocabulary.controlled_subject_area_options,
            text=subject.additional_name,
            collection_index=context.compute_next_collection_index('project/research_field/title'),
            set_index=0,
            set_prefix='',
        )
        if value and value.option:
            existing_options.add(model_key(value.option, value.option.uri_path))


def _write_geo_location(context: ProjectWriteContext, locations: list[GeoLocation]) -> None:
    if not locations:
        return
    location = locations[0]
    context.add('project/dataset/usage_technology/geo_location', location.region)
    if location.country or location.has_any_coordinate:
        context.warn('geoLocations', 'Only the confirmed region mapping was imported')
    if len(locations) > 1:
        context.warn('geoLocations', 'Only the first geolocation was imported')
