"""Reusable vocabulary-backed dataset fields; profiles supply catalog crosswalks."""

from ..types import Resource, Rights, Software, SubjectArea
from ..values import answer_label
from .contracts import Source


def read_subjects(context, *, source: Source, option_map, target, uncertain_options=()):
    context = source.context(context)
    path = source.attribute
    subjects = []
    values = context.get_values(path)
    mapped = context.map_options(
        path,
        option_map,
        values=values,
    )
    for value, controlled in zip(values, mapped, strict=True):
        if not value.is_true:
            context.record_mapping(
                target,
                sources=(value,),
                outcome='skipped',
                reason='Answer is not selected',
            )
            continue
        option_path = value.option.uri_path if value.option else None
        if controlled is None:
            controlled = ('Other',)
            context.warn(
                target,
                path,
                'Unmapped subject preserved as Other',
                answer_label(value),
            )
        elif isinstance(controlled, str):
            controlled = (controlled,)
        if option_path in uncertain_options:
            context.warn(
                target,
                path,
                'Workbook mapping is uncertain; preserved as Other',
                answer_label(value),
            )
        for name in controlled:
            subject = SubjectArea(name, answer_label(value) if name == 'Other' else None)
            if subject not in subjects:
                index = len(subjects)
                context.record_mapping(
                    f'{target}[{index}].controlled_name',
                    sources=(value,),
                    value=name,
                    outcome='defaulted' if name == 'Other' else 'mapped',
                    reason='Subject vocabulary mapping',
                )
                if subject.additional_name:
                    context.record_mapping(
                        f'{target}[{index}].additional_name',
                        sources=(value,),
                        value=subject.additional_name,
                        reason='Preserved subject label',
                    )
                subjects.append(subject)
            else:
                context.record_mapping(target, sources=(value,), outcome='skipped', reason='Duplicate subject')
    if not values:
        context.record_empty_mapping(target, path)
    return subjects


def read_data_sources(context, *, source: Source, option_map, target):
    context = source.context(context)
    sources = []
    path = source.attribute
    values = context.get_values(path)
    mapped = context.map_options(path, option_map, values=values)
    for value, detail in zip(values, mapped, strict=True):
        source = answer_label(value)
        if not source:
            context.record_mapping(target, sources=(value,), outcome='empty', reason='No source label')
            continue
        fallback = detail is None
        if fallback:
            detail = 'Other'
            context.warn(target, path, 'Unmapped creation method preserved as Other', source)
        index = len(sources)
        context.record_mapping(f'{target}[{index}].value', sources=(value,), value=source, reason='Answer label')
        context.record_mapping(
            f'{target}[{index}].resource_type',
            sources=(value,),
            value=detail,
            outcome='defaulted' if fallback else 'mapped',
            reason='Creation-method vocabulary mapping',
        )
        sources.append(Resource(source, detail))
    if not values:
        context.record_empty_mapping(target, path)
    return sources


def read_rights(context, *, source: Source, option_map, target):
    context = source.context(context)
    path = source.attribute
    all_values = context.get_values(path)
    values = [value for value in all_values if value.is_true]
    for value in all_values:
        if not value.is_true:
            context.record_mapping(target, sources=(value,), outcome='skipped', reason='Answer is not selected')
    if not values:
        context.record_empty_mapping(target, path)
        return None
    rights = []
    selected = []
    mapped = context.map_options(path, option_map, values=values)
    for value, controlled in zip(values, mapped, strict=True):
        additional = value.text or (answer_label(value) if not controlled or controlled == 'Other' else None)
        right = Rights(controlled or 'Other', additional)
        if right not in rights:
            rights.append(right)
            selected.append((value, controlled))
        else:
            context.record_mapping(target, sources=(value,), outcome='skipped', reason='Duplicate license')
    if len(rights) > 1:
        context.warn(
            target,
            path,
            'Multiple licenses selected; choose the applicable license in RADAR',
            '; '.join(answer_label(value) for value in values),
        )
        context.record_mapping(target, sources=values, outcome='rejected', reason='Multiple licenses selected')
        return None
    value, controlled = selected[0]
    context.record_mapping(
        f'{target}.controlled',
        sources=(value,),
        value=rights[0].controlled,
        outcome='defaulted' if controlled is None else 'mapped',
        reason='License vocabulary mapping',
    )
    if rights[0].additional:
        context.record_mapping(
            f'{target}.additional', sources=(value,), value=rights[0].additional, reason='Preserved license details'
        )
    return rights[0]


def read_software(context, *, source: Source, option_map, target, software_type=None):
    context = source.context(context)
    software = []
    path = source.attribute
    values = context.get_values(path)
    mapped = context.map_options(path, option_map, values=values)
    for value, required in zip(values, mapped, strict=True):
        if required and value.text and value.text.strip():
            index = len(software)
            context.record_mapping(
                f'{target}[{index}].name', sources=(value,), value=value.text.strip(), reason='Normalized software name'
            )
            context.record_mapping(
                f'{target}[{index}].software_type',
                value=software_type,
                outcome='defaulted',
                reason='Software requirement category',
            )
            software.append(Software(value.text.strip(), software_type))
            context.warn(f'{target}.softwareVersion', path, 'Software version is unavailable; complete it in RADAR')
        else:
            context.record_mapping(
                target,
                sources=(value,),
                outcome='skipped',
                reason='No applicable software requirement or software name',
            )
    if not values:
        context.record_empty_mapping(target, path)
    return software
