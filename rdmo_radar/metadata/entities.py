"""Reusable readers for text/provider names, retaining native Value provenance."""
from .normalization import normalize_answer
from .types import PersonOrOrganization


def normalized_answers(context, path, target, *, scheme=None):
    for value in context.get_values(path):
        if value.option is not None:
            context.warn(target, path, 'An Option or responsibility selection is not an entity name')
            context.record_mapping(target, sources=(value,), outcome='skipped', reason='Option is not an entity name')
            continue
        if not (value.text or value.external_id):
            continue
        answer = normalize_answer(value.text, value.external_id, scheme=scheme)
        for issue in answer.issues:
            context.warn(target, path, issue)
        if answer.label:
            yield value, answer
        else:
            context.record_mapping(target, sources=(value,), outcome='rejected', reason='Missing usable name')


def record_entity(context, person, sources, target):
    context.record_mapping(f'{target}.name', sources=sources, value=person.name, reason='Normalized entity name')
    for index, identifier in enumerate(person.identifiers):
        for field in ('value', 'identifier_type', 'scheme_uri'):
            value = getattr(identifier, field)
            if value is not None:
                context.record_mapping(f'{target}.identifiers[{index}].{field}', sources=sources,
                                       value=value, reason='Provider identifier')


def read_named_values(context, path, *, target, scheme=None):
    """Read a list; target is a canonical prefix such as rights_holders."""
    people, seen = [], set()
    for value, answer in normalized_answers(context, path, target, scheme=scheme):
        identity = (answer.label, answer.identifier.value if answer.identifier else None,
                    answer.identifier.identifier_type if answer.identifier else None)
        if identity in seen:
            context.record_mapping(target, sources=(value,), outcome='skipped', reason='Duplicate entity')
            continue
        seen.add(identity)
        person = PersonOrOrganization(answer.label, identifiers=[answer.identifier] if answer.identifier else [])
        record_entity(context, person, (value,), f'{target}[{len(people)}]')
        people.append(person)
    if not people:
        context.record_empty_mapping(target, path)
    return people


def read_named_value(context, path, *, target, scheme=None):
    """Read one entity without arbitrarily choosing among conflicting answers."""
    answers = list(normalized_answers(context, path, target, scheme=scheme))
    identities = {(answer.label, answer.identifier.value if answer.identifier else None,
                   answer.identifier.identifier_type if answer.identifier else None) for _, answer in answers}
    if len(identities) > 1:
        context.warn(target, path, 'Multiple answers for a scalar field')
        context.record_mapping(f'{target}.name', sources=[value for value, _ in answers], outcome='rejected',
                               reason='Multiple entity answers')
        return None
    if not answers:
        context.record_empty_mapping(f'{target}.name', path)
        return None
    answer = answers[0][1]
    person = PersonOrOrganization(answer.label, identifiers=[answer.identifier] if answer.identifier else [])
    record_entity(context, person, [value for value, _ in answers], target)
    return person


def prefer_name_source(context, preferred, legacy, *, target):
    """Choose a whole source family; ambiguity must not silently enable fallback."""
    issue_count = len(context.issues)
    new_values = [value for path in preferred for value in context.get_values(path)]
    blocked = (len(context.issues) != issue_count or any(value.option is not None for value in new_values)
               or any(issue.source in preferred and issue.reason == 'Ambiguous Attribute' for issue in context.issues))
    old_values = [value for path in legacy for value in context.get_values(path)]
    has_names = any(value.text.strip() and value.option is None for value in new_values)
    if has_names or blocked:
        if any(value.text.strip() and value.option is None for value in old_values):
            context.warn(target, preferred[0], 'Both source families are populated; preferred TF source retained')
        for value in old_values:
            context.record_mapping(target, sources=(value,), outcome='skipped', reason='Preferred TF source selected')
        return True
    return False


def read_controlled_value(context, path, options, *, target):
    """Accept vocabulary identities or exact canonical values, never translated labels."""
    values = [value for value in context.get_values(path) if value.is_true]
    if not values:
        context.record_empty_mapping(target, path)
        return None
    mapped = context.map_options(path, options, values=values)
    canonical = set(options.values())
    choices = {option if value.option is not None else value.text.strip() if value.text.strip() in canonical else None
               for value, option in zip(values, mapped, strict=True)}
    if len(choices) != 1 or None in choices:
        context.warn(target, path, 'Unknown or conflicting controlled value')
        context.record_mapping(target, sources=values, outcome='rejected',
                               reason='Unknown or conflicting controlled value')
        return None
    choice = choices.pop()
    context.record_mapping(target, sources=values, value=choice, reason='Explicit controlled value')
    return choice
