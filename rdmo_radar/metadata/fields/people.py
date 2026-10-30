"""Grouped people and affiliations, independent of catalog Attribute paths."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from types import MappingProxyType

from ..entities import read_controlled_value, read_named_value, read_named_values
from ..normalization import normalize_answer, normalize_identifier
from ..provenance import rebase_attempts
from ..types import Affiliation, Identifier, PersonOrOrganization
from .contracts import AttributeSelector, GroupSpec


@dataclass(frozen=True)
class IdentifierSource:
    value: AttributeSelector
    scheme: str | None = None
    scheme_source: AttributeSelector | None = None
    option_map: Mapping = dataclass_field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, 'option_map', MappingProxyType(dict(self.option_map)))


@dataclass(frozen=True)
class AffiliationSources:
    name: AttributeSelector
    identifier: IdentifierSource | None = None
    autocomplete: AttributeSelector | None = None


@dataclass(frozen=True)
class RoleSource:
    attribute: AttributeSelector
    require_shared_placement: bool = False


@dataclass(frozen=True)
class PersonSources:
    group: GroupSpec
    name: AttributeSelector
    given_name: AttributeSelector | None = None
    family_name: AttributeSelector | None = None
    autocomplete: AttributeSelector | None = None
    identifiers: tuple[IdentifierSource, ...] = ()
    name_type: AttributeSelector | None = None
    name_type_options: Mapping = dataclass_field(default_factory=dict)
    default_name_type: str | None = None
    affiliations: AffiliationSources | None = None
    roles: tuple[RoleSource, ...] = ()
    role_options: Mapping = dataclass_field(default_factory=dict)
    default_role: str | None = None
    role_warnings: Mapping = dataclass_field(default_factory=dict)

    def __post_init__(self):
        for name in ('name_type_options', 'role_options', 'role_warnings'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        for name in ('identifiers', 'roles'):
            object.__setattr__(self, name, tuple(getattr(self, name)))


def read_people(
    context, *, sources: PersonSources, target, normalizer=normalize_answer, identifier_normalizer=normalize_identifier,
    repeat_roles=False, start_index=0,
):
    if not isinstance(start_index, int) or start_index < 0:
        raise ValueError('The starting person index must be a nonnegative integer.')
    parent = sources.group.context(context)
    report_orphan_identities(parent, sources, target)
    people = []
    groups = parent.groups(*sources.group.anchors)
    for group in groups:
        item_target = f'{target}[{start_index + len(people)}]'
        trace_start = len(parent.provenance) if parent.provenance is not None else 0
        person = _read_person_or_organization(
            group,
            sources,
            item_target,
            parent=parent,
            normalizer=normalizer,
            identifier_normalizer=identifier_normalizer,
        )
        if person is not None:
            if repeat_roles and (sources.roles or sources.default_role is not None):
                related = parent.descendants(group, sources.group.anchors)
                evidence = tuple(parent.provenance[trace_start:]) if parent.provenance is not None else ()
                people.extend(_expand_person_roles(
                    related, sources, person, target=target, start_index=start_index + len(people),
                    evidence=evidence, parent=parent,
                ))
                continue
            if sources.roles or sources.default_role is not None:
                related = parent.descendants(group, sources.group.anchors)
                person.contributor_type = _read_role(related, sources, item_target, parent=parent)
            people.append(person)
    if not groups:
        parent.record_empty_mapping(target, sources.name)
    return people


def _expand_person_roles(context, sources, person, *, target, start_index, evidence, parent):
    """Expand a constructed person, copying its evidence to each additional role entry."""
    item_target = f'{target}[{start_index}]'
    roles = _read_repeated_roles(context, sources, item_target, parent=parent)
    people = []
    for offset, (role, role_evidence, defaulted) in enumerate(roles):
        expanded_target = f'{target}[{start_index + offset}]'
        if offset and context.provenance is not None:
            context.provenance.extend(rebase_attempts(
                (attempt for attempt in evidence if attempt.field.startswith(item_target)),
                {item_target: expanded_target},
            ))
        context.record_mapping(
            f'{expanded_target}.contributor_type', sources=role_evidence, value=role,
            outcome='defaulted' if defaulted else 'mapped',
            reason='Role retained as Other' if defaulted else 'Explicit contributor role',
        )
        people.append(replace(person, contributor_type=role))
    return people


def _read_repeated_roles(context, sources, target, *, parent):
    evidence = {}
    defaulted = set()
    for source in sources.roles:
        path = source.attribute
        if source.require_shared_placement and not context.has_shared_placement(path, sources.group.anchors):
            if parent.get_values(path):
                context.warn(target, path, 'Contributor role alias has no shared catalog group')
            continue
        values = context.get_values(path)
        mapped = context.map_options(path, sources.role_options, values=values)
        for value, role in zip(values, mapped, strict=True):
            if not value.is_true:
                context.record_mapping(f'{target}.contributor_type', sources=(value,), outcome='skipped',
                                       reason='Answer is not selected')
                continue
            if value.option is None:
                role = value.text.strip() if value.text.strip() in sources.role_options.values() else None
            warning = sources.role_warnings.get(value.option.uri) if value.option else None
            if role is None:
                warning = 'Unknown contributor role; retained as Other'
                role = 'Other'
                defaulted.add(role)
                context.record_mapping(f'{target}.contributor_type', sources=(value,), outcome='rejected',
                                       reason=warning)
            if warning:
                context.warn(target, path, warning)
            evidence.setdefault(role, []).append(value)
    if not evidence:
        context.warn(target, sources.name, 'No contributor role supplied; retained as Other')
        return [('Other', (), True)]
    order = list(dict.fromkeys(sources.role_options.values()))
    return [(role, evidence[role], role in defaulted)
            for role in sorted(evidence, key=lambda r: (r == 'Other', order.index(r) if r in order else len(order)))]


def report_orphan_identities(context, sources, target):
    paths = (
        tuple(item.value for item in sources.identifiers)
        + tuple(item.attribute for item in sources.roles)
        + ((sources.name_type,) if sources.name_type else ())
    )
    anchors = sources.group.anchors
    claimed = set()
    for group in context.groups(*anchors):
        if any(value.text.strip() and value.option is None for path in anchors for value in group.get_values(path)):
            scoped = context.descendants(group, anchors)
            claimed.update(id(value) for path in paths for value in scoped.get_values(path))
    orphan_values = [
        value for path in paths for value in context.get_values(path) if value.is_true and id(value) not in claimed
    ]
    if orphan_values:
        context.warn(target, sources.name, 'Identifier/type-only entries do not establish an entity name')
        context.record_mapping(target, sources=orphan_values, outcome='rejected', reason='Missing entity name')


def _read_name(context, sources, target, normalizer):
    start = len(context.provenance) if context.provenance is not None else 0
    person = read_named_value(context, sources.name, target=target, normalizer=normalizer)
    autocomplete = (
        read_named_value(context, sources.autocomplete, target=target, scheme='ORCID', normalizer=normalizer)
        if sources.autocomplete
        else None
    )
    name = person.name if person else None
    identifiers = list(person.identifiers) if person else []
    if autocomplete:
        identifiers.extend(autocomplete.identifiers)
        name = name or autocomplete.name
    given_name = context.get_text(sources.given_name, target=f'{target}.given_name') if sources.given_name else None
    family_name = context.get_text(sources.family_name, target=f'{target}.family_name') if sources.family_name else None
    if not name:
        name = ', '.join(value for value in (family_name, given_name) if value)
        if name and context.provenance is not None:
            sources = []
            for attempt in context.provenance[start:]:
                if attempt.field in (f'{target}.given_name', f'{target}.family_name') and attempt.outcome == 'mapped':
                    sources.extend(attempt.sources)
            context.record_mapping(
                f'{target}.name',
                sources=sources,
                value=name,
                outcome='defaulted',
                reason='Name composed from family and given names',
            )
    return name, given_name, family_name, identifiers


def _read_person_or_organization(context, sources, target, *, parent, normalizer, identifier_normalizer):
    context = parent.descendants(context, sources.group.anchors)
    start = len(context.provenance) if context.provenance is not None else 0
    name, given_name, family_name, identifiers = _read_name(context, sources, target, normalizer)
    if not name:
        if context.get_scope_values():
            context.warn(target, sources.name, 'Identifier/type-only entries do not establish an entity name')
        return None
    identifiers = _read_identifiers(context, sources, target, identifiers, normalizer, identifier_normalizer,
                                    provenance_start=start)
    name_type = (
        read_controlled_value(context, sources.name_type, sources.name_type_options, target=f'{target}.name_type')
        if sources.name_type
        else None
    )
    if name_type is None:
        schemes = {identifier.identifier_type for identifier in identifiers}
        name_type = (
            'Organizational'
            if 'ROR' in schemes
            else ('Personal' if given_name or family_name or 'ORCID' in schemes else sources.default_name_type)
        )
        if name_type:
            evidence_fields = set()
            reason = 'Established source category default'
            scheme = 'ROR' if 'ROR' in schemes else 'ORCID' if 'ORCID' in schemes else None
            if scheme:
                reason = f'Entity type inferred from {scheme} identifier'
                evidence_fields = {
                    f'{target}.identifiers[{index}].value'
                    for index, identifier in enumerate(identifiers) if identifier.identifier_type == scheme
                }
            elif given_name or family_name:
                reason = 'Person inferred from structured name'
                evidence_fields = {f'{target}.given_name', f'{target}.family_name'}
            evidence = {}
            for attempt in (context.provenance or ())[start:]:
                if attempt.field in evidence_fields and not attempt.unsuccessful:
                    for source in attempt.sources:
                        evidence[id(source.value)] = source
            context.record_mapping(
                f'{target}.name_type',
                sources=evidence.values(),
                value=name_type,
                outcome='defaulted',
                reason=reason,
            )
    elif (name_type == 'Personal' and any(item.identifier_type == 'ROR' for item in identifiers)) or (
        name_type == 'Organizational' and any(item.identifier_type == 'ORCID' for item in identifiers)
    ):
        context.warn(target, sources.name, 'Entity type conflicts with identifier; identity omitted')
        identifiers = []
    return PersonOrOrganization(
        name=name,
        given_name=given_name,
        family_name=family_name,
        name_type=name_type,
        identifiers=identifiers,
        affiliations=_read_affiliations(parent, context, sources, target, normalizer, identifier_normalizer),
    )


def _read_identifiers(context, sources, target, identifiers, normalizer, identifier_normalizer, *, provenance_start):
    evidence = []
    conflicting = False
    for path, hint in ((sources.name, None), (sources.autocomplete, 'ORCID')):
        if path is None:
            continue
        for value in context.get_values(path):
            if value.option is not None:
                continue
            answer = normalizer(value.text, value.external_id, scheme=hint)
            if any('conflict' in issue.lower() for issue in answer.issues):
                conflicting = True
            if answer.identifier in identifiers:
                evidence.append((answer.identifier, (value,)))
    for item in sources.identifiers:
        path, scheme_path = item.value, item.scheme_source
        scheme = (
            read_controlled_value(
                context, scheme_path, item.option_map, target=f'{target}.identifiers[0].identifier_type'
            )
            if scheme_path
            else None
        )
        expected = scheme if scheme_path else item.scheme
        input_values = context.get_values(path)
        value = context.get_identifier(path, target=f'{target}.identifiers[0].value')
        if not value:
            if any(value.external_id or value.text.strip() for value in input_values):
                conflicting = True
            continue
        if not expected:
            context.warn(target, path, 'Identifier has no recognized scheme')
            conflicting = True
            continue
        detected = identifier_normalizer(value)
        if detected and detected.identifier_type != expected:
            context.warn(target, path, 'Identifier scheme conflicts with its URI')
            conflicting = True
            continue
        identifier = identifier_normalizer(value, expected) or Identifier(value, expected)
        if scheme_path:
            input_values = [*input_values, *context.get_values(scheme_path)]
        evidence.append((identifier, input_values))
    by_scheme = {}
    for identifier, _ in evidence:
        by_scheme.setdefault(identifier.identifier_type, {})[identifier.value] = identifier
    if conflicting or {'ROR', 'ORCID'} <= by_scheme.keys() or any(len(values) > 1 for values in by_scheme.values()):
        context.warn(target, sources.name, 'Conflicting entity identifiers; identity omitted')
        return []
    result = [next(iter(values.values())) for values in by_scheme.values()]
    if context.provenance is not None:
        # Replace preliminary successful reads with the final, reconciled identity.
        # Keep empty, skipped and rejected attempts as diagnostics.
        context.provenance[provenance_start:] = [
            attempt for attempt in context.provenance[provenance_start:]
            if attempt.unsuccessful or not attempt.field.startswith(f'{target}.identifiers[')
        ]
    for index, identifier in enumerate(result):
        inputs = {id(value): value for item, values in evidence if item == identifier for value in values}
        sources = list(inputs.values())
        for field in ('value', 'identifier_type', 'scheme_uri'):
            value = getattr(identifier, field)
            if value is not None:
                context.record_mapping(
                    f'{target}.identifiers[{index}].{field}',
                    sources=sources,
                    value=value,
                    reason='Normalized entity identifier',
                )
    return result


def _read_affiliations(parent, context, sources, target, normalizer, identifier_normalizer):
    spec = sources.affiliations
    if spec is None:
        return []
    path = spec.name
    id_path = spec.identifier.value if spec.identifier else None
    scheme_path = spec.identifier.scheme_source if spec.identifier else None
    scoped = parent.descendants(context, sources.group.anchors)
    autocomplete_path = spec.autocomplete
    values = scoped.get_values(path)
    if autocomplete_path:
        values = [*values, *scoped.get_values(autocomplete_path)]
    affiliations = []
    groups = {(value.set_prefix, value.set_index) for value in values}
    for prefix, index in sorted(
        groups,
        key=lambda pair: (
            tuple(map(int, pair[0].split('|'))) if pair[0] else (),
            pair[1],
        ),
    ):
        group = parent.descendants(
            parent.group(prefix, index), (path, autocomplete_path) if autocomplete_path else (path,)
        )
        people = read_named_values(group, path, target=f'{target}.affiliations', normalizer=normalizer)
        # Provider-backed affiliation search is a separate sibling in SMP catalogs.
        if autocomplete_path:
            autocomplete = read_named_value(
                group, autocomplete_path, target=f'{target}.affiliations[0]', scheme='ROR', normalizer=normalizer
            )
            if autocomplete:
                if not people:
                    people = [autocomplete]
                elif len(people) == 1:
                    people[0].identifiers.extend(autocomplete.identifiers)
        scheme = (
            read_controlled_value(
                group,
                scheme_path,
                spec.identifier.option_map,
                target=f'{target}.affiliations[{len(affiliations)}].identifier_scheme',
            )
            if scheme_path
            else spec.identifier.scheme
            if spec.identifier
            else None
        )
        raw_id = group.get_identifier(id_path) if id_path else None
        if raw_id and len(people) != 1:
            group.warn(target, id_path, 'Affiliation identifier is ambiguous across multiple names')
        for person in people:
            ids = list(person.identifiers)
            if raw_id and len(people) == 1:
                if scheme:
                    detected = identifier_normalizer(raw_id)
                    if detected and detected.identifier_type != scheme:
                        group.warn(target, id_path, 'Affiliation identifier scheme conflicts with its URI')
                        ids = []
                    else:
                        ids.append(identifier_normalizer(raw_id, scheme) or Identifier(raw_id, scheme))
                else:
                    group.warn(target, id_path, 'Affiliation identifier has no recognized scheme')
            identities = {(identifier.value, identifier.identifier_type) for identifier in ids}
            if len(identities) > 1 or any(identifier.identifier_type == 'ORCID' for identifier in ids):
                group.warn(target, path, 'Conflicting or non-organisational affiliation identifier')
                ids = []
            identifier = ids[0] if ids else None
            affiliation = Affiliation(
                person.name,
                identifier.value if identifier else None,
                identifier.identifier_type if identifier else None,
                identifier.scheme_uri if identifier else None,
            )
            sources = [
                value
                for source in (path, id_path, scheme_path, autocomplete_path)
                if source
                for value in group.get_values(source)
            ]
            for field in ('name', 'identifier', 'identifier_scheme', 'scheme_uri'):
                value = getattr(affiliation, field)
                if value is not None:
                    group.record_mapping(
                        f'{target}.affiliations[{len(affiliations)}].{field}',
                        sources=sources,
                        value=value,
                        reason='Creator-linked organisational affiliation',
                    )
            affiliations.append(affiliation)
    if len(affiliations) > 1:
        context.warn(target, path, 'RADAR accepts one affiliation; only the first is exported')
    return affiliations


def _read_role(context, sources, target, *, parent):
    roles = []
    invalid = False
    for source in sources.roles:
        path = source.attribute
        if source.require_shared_placement and not context.has_shared_placement(path, sources.group.anchors):
            if parent.get_values(path):
                context.warn(target, path, 'Contributor role alias has no shared catalog group')
            continue
        values = context.get_values(path)
        role = read_controlled_value(context, path, sources.role_options, target=f'{target}.contributor_type')
        if values and role is None:
            invalid = True
        if role:
            roles.append(role)
    if invalid or len(set(roles)) > 1:
        context.warn(target, sources.roles[0].attribute, 'Unknown or conflicting contributor roles; default retained')
    if not invalid and len(set(roles)) == 1:
        return roles[0]
    if sources.default_role is not None:
        context.record_mapping(
            f'{target}.contributor_type',
            value=sources.default_role,
            outcome='defaulted',
            reason='No single supported explicit contributor role',
        )
    return sources.default_role
