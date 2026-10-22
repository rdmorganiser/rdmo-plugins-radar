from dataclasses import replace

from .constants import XMLVocabulary
from .crosswalks import CREATION_METHOD_OPTIONS, SOFTWARE_REQUIREMENT, SUBJECT_OPTIONS
from .read_context import ProjectReadContext
from .types import GeoLocation, Identifier, PersonOrOrganization, RadarMetadata, Resource, Rights, Software, SubjectArea
from .values import answer_label, get_option_path, model_key, normalize
from .write_context import ProjectWriteContext


def read_dataset_fields(context: ProjectReadContext) -> RadarMetadata:
    identifier_value = context.get_text('project/dataset/data_publication_pid', target='identifier.value')
    identifier_type = context.get_option(
        'project/dataset/pids/system', XMLVocabulary.identifier_type_options, target='identifier.identifier_type',
    )
    acronym = context.shared().get_text('project/acronym', target='additional_titles[0]')
    resource_value = context.get_text('project/dataset/description', target='resource.value')
    geo_location = context.get_text('project/dataset/usage_technology/geo_location', target='geo_locations[0].region')
    title = context.get_text('project/dataset/title', target='title')
    if not title:
        title = context.get_text('project/dataset/id', target='title')
        if title and context.provenance is not None:
            context.provenance[-1] = replace(
                context.provenance[-1], outcome='defaulted', reason='Dataset ID title fallback',
            )
    return RadarMetadata(
        identifier=Identifier(identifier_value, identifier_type) if identifier_value else None,
        title=title,
        additional_titles=[acronym] if acronym else [],
        keywords=context.shared().get_texts('project/research_question/keywords', target='keywords'),
        language=context.get_option('project/dataset/language', XMLVocabulary.language_options, target='language'),
        subject_areas=_read_subjects(context),
        resource=Resource(resource_value) if resource_value else None,
        geo_locations=[GeoLocation(region=geo_location)] if geo_location else [],
        data_sources=_read_data_sources(context),
        software=_read_software(context),
        processing=context.get_texts('project/dataset/method', target='processing'),
        rights=_read_rights(context),
        rights_holders=[PersonOrOrganization(name=name) for name in context.get_texts(
            'project/dataset/sharing/rights_holder', target='rights_holders[{index}].name',
        )],
    )


def write_dataset_fields(context: ProjectWriteContext, metadata: RadarMetadata) -> None:
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
        if metadata.resource.resource_type:
            context.warn(
                'resource.resourceType', 'No confirmed RDMO resource type mapping', metadata.resource.resource_type
            )
    if metadata.rights:
        context.add_option(
            'project/dataset/sharing/conditions',
            metadata.rights.controlled,
            XMLVocabulary.controlled_rights_options,
            text=metadata.rights.additional,
        )
    for collection_index, holder in enumerate(metadata.rights_holders):
        context.add('project/dataset/sharing/rights_holder', holder.name, collection_index=collection_index)
    for collection_index, source in enumerate(metadata.data_sources):
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
    for collection_index, processing in enumerate(metadata.processing):
        context.add('project/dataset/method', processing, collection_index=collection_index)
    _write_geo_location(context, metadata.geo_locations)
    _warn_unmapped_fields(context, metadata)


def _read_subjects(context: ProjectReadContext) -> list[SubjectArea]:
    subjects = []
    values = context.shared().get_values('project/research_field/title')
    mapped = context.map_options(
        'project/research_field/title',
        {**XMLVocabulary.controlled_subject_area_options, **SUBJECT_OPTIONS},
        values=values,
    )
    for value, controlled in zip(values, mapped, strict=True):
        if not value.is_true:
            context.record_mapping(
                'subject_areas', sources=(value,), outcome='skipped', reason='Answer is not selected',
            )
            continue
        option_path = value.option.uri_path if value.option else None
        if controlled is None:
            controlled = ('Other',)
            context.warn(
                'subjectAreas',
                'project/research_field/title',
                'Unmapped subject preserved as Other',
                answer_label(value),
            )
        elif isinstance(controlled, str):
            controlled = (controlled,)
        if option_path == 'research_fields/211':
            context.warn(
                'subjectAreas',
                'project/research_field/title',
                'Workbook mapping is uncertain; preserved as Other',
                answer_label(value),
            )
        for name in controlled:
            subject = SubjectArea(name, answer_label(value) if name == 'Other' else None)
            if subject not in subjects:
                index = len(subjects)
                context.record_mapping(
                    f'subject_areas[{index}].controlled_name', sources=(value,), value=name,
                    outcome='defaulted' if name == 'Other' else 'mapped', reason='Subject vocabulary mapping',
                )
                if subject.additional_name:
                    context.record_mapping(f'subject_areas[{index}].additional_name', sources=(value,),
                                           value=subject.additional_name, reason='Preserved subject label')
                subjects.append(subject)
            else:
                context.record_mapping('subject_areas', sources=(value,), outcome='skipped', reason='Duplicate subject')
    if not values:
        context.record_empty_mapping('subject_areas', 'project/research_field/title')
    return subjects


def _read_data_sources(context: ProjectReadContext) -> list[Resource]:
    sources = []
    path = 'project/dataset/creation_methods'
    values = context.get_values(path)
    mapped = context.map_options(path, {**XMLVocabulary.data_source_options, **CREATION_METHOD_OPTIONS}, values=values)
    for value, detail in zip(values, mapped, strict=True):
        source = answer_label(value)
        if not source:
            context.record_mapping('data_sources', sources=(value,), outcome='empty', reason='No source label')
            continue
        fallback = detail is None
        if fallback:
            detail = 'Other'
            context.warn(
                'dataSources', 'project/dataset/creation_methods', 'Unmapped creation method preserved as Other', source
            )
        index = len(sources)
        context.record_mapping(f'data_sources[{index}].value', sources=(value,), value=source, reason='Answer label')
        context.record_mapping(f'data_sources[{index}].resource_type', sources=(value,), value=detail,
                               outcome='defaulted' if fallback else 'mapped',
                               reason='Creation-method vocabulary mapping')
        sources.append(Resource(source, detail))
    if not values:
        context.record_empty_mapping('data_sources', path)
    return sources


def _read_rights(context: ProjectReadContext) -> Rights | None:
    path = 'project/dataset/sharing/conditions'
    all_values = context.get_values(path)
    values = [value for value in all_values if value.is_true]
    for value in all_values:
        if not value.is_true:
            context.record_mapping('rights', sources=(value,), outcome='skipped', reason='Answer is not selected')
    if not values:
        context.record_empty_mapping('rights', path)
        return None
    rights = []
    selected = []
    mapped = context.map_options(path, XMLVocabulary.controlled_rights_options, values=values)
    for value, controlled in zip(values, mapped, strict=True):
        additional = value.text or (answer_label(value) if not controlled or controlled == 'Other' else None)
        right = Rights(controlled or 'Other', additional)
        if right not in rights:
            rights.append(right)
            selected.append((value, controlled))
        else:
            context.record_mapping('rights', sources=(value,), outcome='skipped', reason='Duplicate license')
    if len(rights) > 1:
        context.warn(
            'rights', path, 'Multiple licenses selected; choose the applicable license in RADAR',
            '; '.join(answer_label(value) for value in values),
        )
        context.record_mapping('rights', sources=values, outcome='rejected', reason='Multiple licenses selected')
        return None
    value, controlled = selected[0]
    context.record_mapping('rights.controlled', sources=(value,), value=rights[0].controlled,
                           outcome='defaulted' if controlled is None else 'mapped', reason='License vocabulary mapping')
    if rights[0].additional:
        context.record_mapping('rights.additional', sources=(value,), value=rights[0].additional,
                               reason='Preserved license details')
    return rights[0]


def _read_software(context):
    software = []
    path = 'project/dataset/usage_technology'
    values = context.get_values(path)
    mapped = context.map_options(path, {SOFTWARE_REQUIREMENT: True}, values=values)
    for value, required in zip(values, mapped, strict=True):
        if required and value.text and value.text.strip():
            index = len(software)
            context.record_mapping(f'software[{index}].name', sources=(value,), value=value.text.strip(),
                                   reason='Normalized software name')
            context.record_mapping(f'software[{index}].software_type', value='Resource Viewing',
                                   outcome='defaulted', reason='Software requirement category')
            software.append(Software(value.text.strip(), 'Resource Viewing'))
            context.warn('software.softwareVersion', path, 'Software version is unavailable; complete it in RADAR')
        else:
            context.record_mapping('software', sources=(value,), outcome='skipped',
                                   reason='No applicable software requirement or software name')
    if not values:
        context.record_empty_mapping('software', path)
    return software


def _merge_acronym(context: ProjectWriteContext, titles: list[str]) -> None:
    if not titles:
        return
    acronym = titles[0]
    existing = context.get_values('project/acronym')
    if not existing:
        context.add('project/acronym', acronym, dataset=False)
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
            dataset=False,
        )
        if value and value.option:
            existing_options.add(model_key(value.option, value.option.uri_path))


def _write_geo_location(context: ProjectWriteContext, locations: list[GeoLocation]) -> None:
    if not locations:
        return
    location = locations[0]
    context.add('project/dataset/usage_technology/geo_location', location.region)
    if location.country or location.latitude or location.longitude:
        context.warn('geoLocations', 'Only the confirmed region mapping was imported')
    if len(locations) > 1:
        context.warn('geoLocations', 'Only the first geolocation was imported')


def _warn_unmapped_fields(context: ProjectWriteContext, metadata: RadarMetadata) -> None:
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
