from .constants import XMLVocabulary
from .rdmo import RDMOReadContext, RDMOWriteContext, get_option_path, normalize
from .types import Agent, GeoLocation, Identifier, RadarMetadata, Resource, Rights, SubjectArea


def read_dataset_fields(context: RDMOReadContext) -> RadarMetadata:
    identifier_value = context.get_text('project/dataset/data_publication_pid')
    identifier_type = context.get_option(
        'project/dataset/pids/system',
        XMLVocabulary.identifier_type_options,
    )
    acronym = context.export.get_text('project/acronym')
    resource_value = context.get_text('project/dataset/description')
    geo_location = context.get_text('project/dataset/usage_technology/geo_location')
    metadata = RadarMetadata(
        identifier=Identifier(identifier_value, identifier_type) if identifier_value else None,
        title=context.get_text('project/dataset/title'),
        additional_titles=[acronym] if acronym else [],
        keywords=context.export.get_list('project/research_question/keywords'),
        language=context.get_option('project/dataset/language', XMLVocabulary.language_options),
        subject_areas=_read_subjects(context),
        resource=Resource(
            resource_value,
            context.get_option('project/dataset/format', XMLVocabulary.resource_type_general_options),
        ) if resource_value else None,
        geo_locations=[GeoLocation(region=geo_location)] if geo_location else [],
        data_sources=_read_data_sources(context),
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
    for value in context.export.get_set('project/research_field/title'):
        if not value.is_true:
            continue
        option_path = value.option.uri_path if value.option else None
        controlled = XMLVocabulary.controlled_subject_area_options.get(option_path, 'Other')
        subjects.append(SubjectArea(controlled, value.text if controlled == 'Other' else None))
    return subjects


def _read_data_sources(context: RDMOReadContext) -> list[Resource]:
    sources = []
    for value in context.get_values('project/dataset/creation_methods'):
        source = value.text or value.value
        if not source:
            continue
        option_path = value.option.uri_path if value.option else None
        sources.append(Resource(source, XMLVocabulary.data_source_options.get(option_path)))
    return sources


def _read_rights(context: RDMOReadContext) -> Rights | None:
    value = next((value for value in context.get_values('project/dataset/sharing/conditions') if value.is_true), None)
    if value is None:
        return None
    option_path = value.option.uri_path if value.option else None
    controlled = XMLVocabulary.controlled_rights_options.get(option_path, 'Other')
    return Rights(controlled, value.text if controlled == 'Other' else None)


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
            context.warn(field, 'No confirmed RDMO task-force mapping')
