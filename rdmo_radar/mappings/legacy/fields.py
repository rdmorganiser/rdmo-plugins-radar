"""The old get_dataset mapping expressed as ordinary canonical field readers.

First/last answer selection and exact coordinates are deliberate legacy policies.
They do not change the generic ProjectReadContext or the Template Framework.
"""

from functools import partial

from ...metadata.fields import FieldMapping, Source
from ...metadata.types import (
    Affiliation,
    Description,
    FundingReference,
    Identifier,
    MappingSource,
    PersonOrOrganization,
    Resource,
    Rights,
    SubjectArea,
)
from . import vocabulary as options


def read_set(context, attribute, prefix=''):
    return [value for value in context.shared().get_values(attribute) if value.set_prefix == prefix]


def first_value(context, source, target):
    selected = context.shared().group('', 0) if source.scope == 'project' else context
    values = selected.get_values(source.attribute)
    for value in values[1:]:
        selected.record_mapping(target, sources=(value,), outcome='skipped', reason='Legacy first-answer selection')
    if not values:
        selected.record_empty_mapping(target, source.attribute)
        return selected, None
    return selected, values[0]


def first_text(context, *, source, target):
    selected, value = first_value(context, source, target)
    if value is None:
        return None
    selected.record_mapping(target, sources=(value,), value=value.text,
                            outcome='mapped' if value.text else 'empty', reason='Legacy first text answer')
    return value.text


def first_option(context, *, source, option_map, target, default=None):
    selected, value = first_value(context, source, target)
    mapped = selected.map_options(source.attribute, option_map)
    result = mapped[0] if value is not None and value.option is not None else None
    if value is not None and value.option is not None and result is None:
        selected.warn(
            target or source.attribute, source.attribute, 'Unmapped or ambiguous legacy Option', value.option.uri,
        )
    fallback = result is None
    result = default if fallback else result
    selected.record_mapping(
        target, sources=(value,) if value is not None else (), value=result,
        outcome='defaulted' if fallback and result is not None else 'mapped' if result is not None else 'empty',
        reason='Legacy Option default' if fallback else 'Legacy Option mapping',
    )
    return result


def text_list(context, *, source, target):
    selected = context.shared().group('', 0) if source.scope == 'project' else context
    result = []
    values = selected.get_values(source.attribute)
    for value in values:
        if value.text:
            selected.record_mapping(f'{target}[{len(result)}]', sources=(value,), value=value.text,
                                    reason='Legacy ordered text list')
            result.append(value.text)
        else:
            selected.record_mapping(target, sources=(value,), outcome='skipped', reason='Empty legacy list answer')
    if not values:
        selected.record_empty_mapping(target, source.attribute)
    return result


def text_fallback(context, paths, target):
    for path in paths:
        text = first_text(context, source=Source(path), target=target)
        if text:
            return text
    return None


def read_title(context, *, target):
    title = text_fallback(context, ('project/dataset/title', 'project/dataset/id'), target)
    if title:
        return title
    title = f'Dataset #{context.set_index + 1}'
    context.record_mapping(target, sources=(MappingSource('Legacy dataset index', context.set_index),),
                           value=title, outcome='defaulted', reason='Legacy numbered dataset title')
    return title


def read_publishers(context, *, target):
    name = text_fallback(context, ('project/dataset/publisher', 'project/dataset/preservation/repository'),
                         f'{target}[0].name')
    return [PersonOrOrganization(name)] if name else []


def read_year(context, *, paths, target):
    for path in paths:
        selected, value = first_value(context, Source(path), target)
        year = getattr(value.value, 'year', None) if value is not None else None
        if year is not None:
            result = str(year)
            selected.record_mapping(target, sources=(value,), value=result, reason='Legacy typed date year')
            return result
        if value is not None:
            selected.record_mapping(target, sources=(value,), outcome='skipped', reason='Legacy answer is not a date')
    return None


def read_subjects(context, *, target):
    path = 'project/dataset/subject'
    selected = context
    values = context.get_values(path)
    if not values:
        path = 'project/research_field/title'
        selected = context.shared().group('', 0)
        values = selected.get_values(path)
    mapped = selected.map_options(path, options.CONTROLLED_SUBJECT_AREA_OPTIONS)
    result = []
    for value, controlled in zip(values, mapped, strict=True):
        if not value.is_true:
            selected.record_mapping(
                target, sources=(value,), outcome='skipped', reason='Legacy subject is not selected',
            )
            continue
        fallback = controlled is None
        controlled = controlled or 'Other'
        field = f'{target}[{len(result)}]'
        selected.record_mapping(f'{field}.controlled_name', sources=(value,), value=controlled,
                                outcome='defaulted' if fallback else 'mapped',
                                reason='Legacy subject mapping')
        additional = value.value if controlled == 'Other' else None
        if additional is not None:
            selected.record_mapping(f'{field}.additional_name', sources=(value,), value=additional,
                                    reason='Legacy additional subject name')
        result.append(SubjectArea(controlled, additional))
    if not values:
        selected.record_empty_mapping(target, path)
    return result


def read_resource(context, *, target):
    text = first_text(context, source=Source('project/dataset/resource_type'), target=f'{target}.value')
    if not text:
        return None
    kind = first_option(context, source=Source('project/dataset/resource_type_general'),
                        option_map=options.RESOURCE_TYPE_OPTIONS, target=f'{target}.resource_type')
    return Resource(text, kind)


def read_identifiers(context, *, base, related=False, target):
    result = []
    for marker in read_set(context, f'{base}/identifier', str(context.set_index)):
        group = context.group(marker.set_prefix, marker.set_index)
        field = f'{target}[{len(result)}]'
        value = first_text(group, source=Source(f'{base}/identifier'), target=f'{field}.value')
        kind = first_option(group, source=Source(f'{base}/identifier_type'),
                            option_map=options.IDENTIFIER_TYPE_OPTIONS, target=f'{field}.identifier_type')
        relation = first_option(group, source=Source(f'{base}/relation_type'), option_map=options.RELATION_TYPE_OPTIONS,
                                target=f'{field}.relation_type') if related else None
        result.append(Identifier(value, kind, relation))
    return result


def read_rights(context, *, target):
    path = 'project/dataset/sharing/conditions'
    values = context.get_values(path)
    if not values:
        context.record_empty_mapping(target, path)
        return None
    for value in values[:-1]:
        context.record_mapping(target, sources=(value,), outcome='skipped', reason='Legacy last-license selection')
    value = values[-1]
    mapped = context.map_options(path, options.CONTROLLED_RIGHTS_OPTIONS)[-1]
    controlled = mapped or 'Other'
    context.record_mapping(f'{target}.controlled', sources=(value,), value=controlled,
                           outcome='defaulted' if mapped is None else 'mapped', reason='Legacy last license')
    additional = value.value if controlled == 'Other' else None
    if additional is not None:
        context.record_mapping(f'{target}.additional', sources=(value,), value=additional, reason='Legacy rights text')
    return Rights(controlled, additional)


def read_rights_holders(context, *, target):
    path = 'project/dataset/sharing/rights_holder'
    names = []
    values = context.get_values(path)
    for value in values:
        if value.text:
            context.record_mapping(f'{target}[{len(names)}].name', sources=(value,), value=value.text,
                                   reason='Legacy rights-holder text')
            names.append(PersonOrOrganization(value.text))
        else:
            context.record_mapping(target, sources=(value,), outcome='skipped', reason='Empty legacy rights holder')
    if not values:
        context.record_empty_mapping(target, path)
    return names


def read_descriptions(context, *, target):
    text = first_text(context, source=Source('project/dataset/description'), target=f'{target}[0].value')
    if not text:
        return []
    context.record_mapping(f'{target}[0].description_type', value='Abstract', outcome='defaulted',
                           reason='Legacy description category')
    return [Description(text)]


def read_people(context, *, base, contributor=False, target):
    people = []
    for marker in read_set(context, f'{base}/name', str(context.set_index)):
        group = context.group(marker.set_prefix, marker.set_index)
        field = f'{target}[{len(people)}]'
        name = first_text(group, source=Source(f'{base}/name'), target=f'{field}.name')
        if not name:
            continue
        person = PersonOrOrganization(
            name,
            given_name=first_text(group, source=Source(f'{base}/given_name'), target=f'{field}.given_name'),
            family_name=first_text(group, source=Source(f'{base}/family_name'), target=f'{field}.family_name'),
            name_type=first_option(group, source=Source(f'{base}/name_type'), option_map=options.NAME_TYPE_OPTIONS,
                                   target=f'{field}.name_type', default='Personal'),
        )
        if contributor:
            person.contributor_type = first_option(
                group, source=Source(f'{base}/contributor_type'), option_map=options.CONTRIBUTOR_TYPE_OPTIONS,
                target=f'{field}.contributor_type', default='Other',
            )
        identifier = first_text(group, source=Source(f'{base}/name_identifier'), target=f'{field}.identifiers[0].value')
        if identifier:
            kind = first_option(group, source=Source(f'{base}/name_identifier_scheme'),
                                option_map=options.NAME_IDENTIFIER_SCHEME_OPTIONS,
                                target=f'{field}.identifiers[0].identifier_type', default='ORCID')
            person.identifiers.append(Identifier(identifier, kind))
        for value in group.get_values(f'{base}/affiliation'):
            if not value.text:
                group.record_mapping(f'{field}.affiliations', sources=(value,), outcome='empty',
                                     reason='Empty legacy affiliation')
            elif person.affiliations:
                group.record_mapping(f'{field}.affiliations', sources=(value,), outcome='skipped',
                                     reason='Legacy first affiliation only')
            else:
                person.affiliations.append(Affiliation(value.text))
                group.record_mapping(f'{field}.affiliations[0].name', sources=(value,), value=value.text,
                                     reason='Legacy first nonempty affiliation')
        people.append(person)
    if not people:
        context.record_empty_mapping(target, f'{base}/name')
    return people


def read_data_sources(context, *, target):
    text = first_text(context, source=Source('project/dataset/data_source'), target=f'{target}[0].value')
    if not text:
        return []
    kind = first_option(context, source=Source('project/dataset/data_source_detail'),
                        option_map=options.DATA_SOURCE_OPTIONS, target=f'{target}[0].resource_type')
    return [Resource(text, kind)]


def read_funding(context, *, target):
    references = []
    for marker in read_set(context, 'project/funder/id'):
        group = context.group('', marker.set_index)
        field = f'{target}[{len(references)}]'
        reference = FundingReference(
            funder_name=first_text(group, source=Source('project/funder/name'), target=f'{field}.funder_name'),
            award_uri=first_text(group, source=Source('project/funder/programme/url'), target=f'{field}.award_uri'),
            award_number=first_text(
                group, source=Source('project/funder/programme/number'), target=f'{field}.award_number',
            ),
            award_title=first_text(
                group, source=Source('project/funder/programme/title'), target=f'{field}.award_title',
            ),
        )
        identifier = first_text(group, source=Source('project/funder/name_identifier'),
                                target=f'{field}.funder_identifier.value')
        if identifier:
            kind = first_option(group, source=Source('project/funder/name_identifier_scheme'),
                                option_map=options.NAME_IDENTIFIER_SCHEME_OPTIONS,
                                target=f'{field}.funder_identifier.identifier_type', default='Other')
            reference.funder_identifier = Identifier(identifier, kind)
        references.append(reference)
    if not references:
        context.record_empty_mapping(target, 'project/funder/id')
    return references


LEGACY_FIELDS = FieldMapping(readers={
    'title': read_title,
    'creators': partial(read_people, base='project/dataset/creator'),
    'publishers': read_publishers,
    'production_year': partial(read_year, paths=('project/dataset/created', 'project/dataset/data_publication_date')),
    'publication_year': partial(read_year, paths=('project/dataset/issued', 'project/dataset/data_publication_date')),
    'subject_areas': read_subjects,
    'resource': read_resource,
    'alternate_identifiers': partial(read_identifiers, base='project/dataset/alternate_identifier'),
    'related_identifiers': partial(read_identifiers, base='project/dataset/related_identifier', related=True),
    'rights': read_rights,
    'rights_holders': read_rights_holders,
    'descriptions': read_descriptions,
    'keywords': partial(text_list, source=Source('project/research_question/keywords', 'project')),
    'contributors': partial(read_people, base='project/dataset/contributor', contributor=True),
    'language': partial(first_option, source=Source('project/dataset/language'), option_map=options.LANGUAGE_OPTIONS),
    'data_sources': read_data_sources,
    'funding_references': read_funding,
})
