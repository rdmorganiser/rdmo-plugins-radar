from django.utils.html import strip_tags

from .constants import XMLVocabulary
from .crosswalks import CREATION_METHOD_OPTIONS, SOFTWARE_REQUIREMENT, SUBJECT_OPTIONS
from .rdmo import RDMOReadContext, RDMOWriteContext, get_option_path, normalize
from .types import Agent, GeoLocation, Identifier, RadarMetadata, Resource, Rights, Software, SubjectArea


def read_dataset_fields(context: RDMOReadContext) -> RadarMetadata:
    identifier_value = context.get_text('project/dataset/data_publication_pid')
    identifier_type = context.get_option(
        'project/dataset/pids/system',
        XMLVocabulary.identifier_type_options,
    )
    acronym = context.shared().get_text('project/acronym')
    resource_value = context.get_text('project/dataset/description')
    geo_location = context.get_text('project/dataset/usage_technology/geo_location')
    metadata = RadarMetadata(
        identifier=Identifier(identifier_value, identifier_type) if identifier_value else None,
        title=context.get_text('project/dataset/title') or context.get_text('project/dataset/id'),
        additional_titles=[acronym] if acronym else [],
        keywords=context.shared().get_texts('project/research_question/keywords'),
        language=context.get_option('project/dataset/language', XMLVocabulary.language_options),
        subject_areas=_read_subjects(context),
        resource=Resource(
            resource_value,
            context.get_option('project/dataset/format', XMLVocabulary.resource_type_general_options),
        ) if resource_value else None,
        geo_locations=[GeoLocation(region=geo_location)] if geo_location else [],
        data_sources=_read_data_sources(context),
        software=_read_software(context),
        processing=context.get_texts('project/dataset/method'),
        rights=_read_rights(context),
        rights_holders=[
            Agent(name=name) for name in context.get_texts('project/dataset/ipr/owner/name')
        ],
    )
    return metadata


def write_dataset_fields(context: RDMOWriteContext, metadata: RadarMetadata) -> None:
    context.add('project/dataset/title', metadata.title)
    if metadata.identifier:
        context.add('project/dataset/data_publication_pid', metadata.identifier.value)
        context.add_option(
            'project/dataset/pids/system',
            metadata.identifier.identifier_type,
            XMLVocabulary.identifier_type_options,
        )
    _merge_acronym(context, metadata.additional_titles)
    for keyword in metadata.keywords:
        context.add_unique_text('project/research_question/keywords', keyword)
    _merge_subjects(context, metadata.subject_areas)
    context.add_option('project/dataset/language', metadata.language, XMLVocabulary.language_options)
    if metadata.resource:
        context.add('project/dataset/description', metadata.resource.value)
        context.add_option(
            'project/dataset/format',
            metadata.resource.resource_type,
            XMLVocabulary.resource_type_general_options,
        )
    if metadata.rights:
        context.add_option(
            'project/dataset/sharing/conditions',
            metadata.rights.controlled,
            XMLVocabulary.controlled_rights_options,
            text=metadata.rights.additional,
        )
    for index, holder in enumerate(metadata.rights_holders):
        context.add('project/dataset/ipr/owner/name', holder.name, collection_index=index)
    for index, source in enumerate(metadata.data_sources):
        if source.resource_type:
            context.add_option(
                'project/dataset/creation_methods',
                source.resource_type,
                XMLVocabulary.data_source_options,
                text=source.value,
                collection_index=index,
            )
        else:
            context.add('project/dataset/creation_methods', source.value, collection_index=index)
    for index, processing in enumerate(metadata.processing):
        context.add('project/dataset/method', processing, collection_index=index)
    _write_geo_location(context, metadata.geo_locations)
    _warn_unmapped_fields(context, metadata)


def _read_subjects(context: RDMOReadContext) -> list[SubjectArea]:
    subjects = []
    values = (context.shared().get_values('project/research_field/title') if context.index is not None
              else context.export.get_set('project/research_field/title'))
    for value in values:
        if not value.is_true:
            continue
        option_path = value.option.uri_path if value.option else None
        controlled = SUBJECT_OPTIONS.get(option_path)
        if controlled is None:
            known = XMLVocabulary.controlled_subject_area_options.get(option_path)
            controlled = (known or 'Other',)
            if known is None:
                context.warn('subjectAreas', 'project/research_field/title',
                             'Unmapped subject preserved as Other', _answer_label(value))
        if option_path == 'research_fields/211':
            context.warn('subjectAreas', 'project/research_field/title',
                         'Workbook mapping is uncertain; preserved as Other', _answer_label(value))
        for name in controlled:
            subject = SubjectArea(name, _answer_label(value) if name == 'Other' else None)
            if subject not in subjects:
                subjects.append(subject)
    return subjects


def _read_data_sources(context: RDMOReadContext) -> list[Resource]:
    sources = []
    for value in context.get_values('project/dataset/creation_methods'):
        source = _answer_label(value)
        if not source:
            continue
        option_path = value.option.uri_path if value.option else None
        detail = CREATION_METHOD_OPTIONS.get(option_path) or XMLVocabulary.data_source_options.get(option_path)
        if detail is None:
            detail = 'Other'
            context.warn('dataSources', 'project/dataset/creation_methods',
                         'Unmapped creation method preserved as Other', source)
        sources.append(Resource(source, detail))
    return sources


def _read_rights(context: RDMOReadContext) -> Rights | None:
    path = 'project/dataset/sharing/conditions'
    values = [value for value in context.get_values(path) if value.is_true]
    if not values:
        return None
    rights = []
    for value in values:
        option_path = value.option.uri_path if value.option else None
        controlled = XMLVocabulary.controlled_rights_options.get(option_path, 'Other')
        additional = value.text or (_answer_label(value) if controlled == 'Other' else None)
        right = Rights(controlled, additional)
        if right not in rights:
            rights.append(right)
    if len(rights) > 1:
        context.warn('rights', path, 'Multiple licenses selected; choose the applicable license in RADAR',
                     '; '.join(_answer_label(value) for value in values))
        return None
    return rights[0]


def _answer_label(value):
    """Read option labels without Value.value's rendered display HTML."""
    label = strip_tags(str(value.option.text)) if value.option else ''
    text = value.text.strip() if value.text else ''
    return f'{label}: {text}' if label and text and label != text else text or label


def _read_software(context):
    software = []
    path = 'project/dataset/usage_technology'
    for value in context.get_values(path):
        if value.option and value.option.uri_path == SOFTWARE_REQUIREMENT and value.text and value.text.strip():
            software.append(Software(value.text.strip(), 'Resource Viewing'))
            context.warn('software.softwareVersion', path, 'Software version is unavailable; complete it in RADAR')
    return software


def _merge_acronym(context: RDMOWriteContext, titles: list[str]) -> None:
    if not titles:
        return
    acronym = titles[0]
    existing = context.values_for('project/acronym')
    if not existing:
        context.add('project/acronym', acronym, dataset=False)
    elif all(normalize(value.text) != normalize(acronym) for value in existing):
        context.warn('project/acronym', 'Existing project acronym was preserved', acronym)
    if len(titles) > 1:
        context.warn('additionalTitles', 'Only one project acronym can be mapped')


def _merge_subjects(context: RDMOWriteContext, subjects: list[SubjectArea]) -> None:
    existing_paths = {
        value.option.uri_path for value in context.values_for('project/research_field/title') if value.option
    }
    for subject in subjects:
        option_path = get_option_path(XMLVocabulary.controlled_subject_area_options, subject.controlled_name)
        if option_path in existing_paths:
            continue
        value = context.add_option(
            'project/research_field/title',
            subject.controlled_name,
            XMLVocabulary.controlled_subject_area_options,
            text=subject.additional_name,
            collection_index=context.next_collection_index('project/research_field/title'),
            dataset=False,
        )
        if value and value.option:
            existing_paths.add(value.option.uri_path)


def _write_geo_location(context: RDMOWriteContext, locations: list[GeoLocation]) -> None:
    if not locations:
        return
    location = locations[0]
    context.add('project/dataset/usage_technology/geo_location', location.region)
    if location.country or location.latitude or location.longitude:
        context.warn('geoLocations', 'Only the confirmed region mapping was imported')
    if len(locations) > 1:
        context.warn('geoLocations', 'Only the first geolocation was imported')


def _warn_unmapped_fields(context: RDMOWriteContext, metadata: RadarMetadata) -> None:
    populated = {
        'alternateIdentifiers': metadata.alternate_identifiers,
        'relatedIdentifiers': metadata.related_identifiers,
        'descriptions': metadata.descriptions,
        'publishers': metadata.publishers,
        'productionYear': metadata.production_year,
        'publicationYear': metadata.publication_year,
        'software': metadata.software,
        'relatedInformation': metadata.related_information,
        'version': metadata.version,
    }
    for field, value in populated.items():
        if value:
            context.warn(field, 'No confirmed RDMO Template Framework mapping')
