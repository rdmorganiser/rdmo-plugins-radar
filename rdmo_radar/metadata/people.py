from dataclasses import replace

from .constants import XMLVocabulary
from .entities import prefer_name_source, read_controlled_value, read_named_value, read_named_values
from .normalization import normalize_answer, normalize_identifier
from .read_context import ProjectReadContext
from .types import Affiliation, Identifier, PersonOrOrganization
from .values import coordinates, matches_placement, normalize, select_values
from .write_context import ProjectWriteContext

CREATOR_NAME = 'project/dataset/creator/name'
CONTRIBUTOR_NAME = 'project/partner/name'


def read_creators(context: ProjectReadContext) -> list[PersonOrOrganization]:
    creators = []
    owner, legacy = 'project/dataset/owner', 'project/dataset/creator'
    base = owner if prefer_name_source(context, _name_paths(owner), _name_paths(legacy), target='creators') else legacy
    _report_orphan_identities(context, owner, 'creators')
    if base == legacy:
        _report_orphan_identities(context, legacy, 'creators')
    groups = context.groups(*_name_paths(base))
    for group in groups:
        creator = _read_person_or_organization(group, base, f'creators[{len(creators)}]', parent=context)
        if creator is not None:
            creators.append(creator)
    if not groups:
        context.record_empty_mapping('creators', CREATOR_NAME)
    return creators


def read_contributors(context: ProjectReadContext) -> list[PersonOrOrganization]:
    contributors = []
    shared = context.shared()
    preferred, legacy = 'project/contributor', 'project/partner'
    names = (*_name_paths(preferred), f'{preferred}/orcid-autocomplete')
    base = preferred if prefer_name_source(shared, names, _name_paths(legacy), target='contributors') else legacy
    _report_orphan_identities(shared, preferred, 'contributors')
    if base == legacy:
        _report_orphan_identities(shared, legacy, 'contributors')
    groups = shared.groups(*_name_paths(base), f'{base}/orcid-autocomplete')
    for group in groups:
        target = f'contributors[{len(contributors)}]'
        contributor = _read_person_or_organization(group, base, target, parent=shared)
        if contributor is not None:
            related = _descendant_context(shared, group, (*_name_paths(base), f'{base}/orcid-autocomplete'))
            contributor.contributor_type = _read_role(related, base, target, parent=shared)
            contributors.append(contributor)
    if not groups:
        context.record_empty_mapping('contributors', CONTRIBUTOR_NAME)
    return contributors


def write_creators(context: ProjectWriteContext, creators: list[PersonOrOrganization]) -> None:
    set_prefix = str(context.dataset_index)
    for set_index, creator in enumerate(creators):
        context.add(CREATOR_NAME, creator.name, set_prefix=set_prefix, set_index=set_index)
        context.add(
            'project/dataset/creator/given_name', creator.given_name, set_prefix=set_prefix, set_index=set_index
        )
        context.add(
            'project/dataset/creator/family_name', creator.family_name, set_prefix=set_prefix, set_index=set_index
        )
        context.add_option(
            'project/dataset/creator/name_type',
            creator.name_type,
            XMLVocabulary.name_type_options,
            set_prefix=set_prefix,
            set_index=set_index,
        )
        if creator.identifiers:
            identifier = creator.identifiers[0]
            context.add(
                'project/dataset/creator/name_identifier',
                identifier.value,
                set_prefix=set_prefix,
                set_index=set_index,
            )
            context.add_option(
                'project/dataset/creator/name_identifier_scheme',
                identifier.identifier_type,
                XMLVocabulary.name_identifier_scheme_options,
                set_prefix=set_prefix,
                set_index=set_index,
            )
            if len(creator.identifiers) > 1:
                context.warn('creators.nameIdentifier', 'Only the first creator identifier was imported')
        if creator.affiliations:
            affiliation = creator.affiliations[0]
            context.add(
                'project/dataset/creator/affiliation',
                affiliation.name,
                set_prefix=set_prefix,
                set_index=set_index,
            )
            if len(creator.affiliations) > 1:
                context.warn('creators.affiliation', 'Only the first creator affiliation was imported')
            if affiliation.identifier or affiliation.scheme_uri:
                context.warn('creators.affiliation',
                             'Only affiliation names have an established RDMO import destination')


def merge_contributors(context: ProjectWriteContext, contributors: list[PersonOrOrganization]) -> None:
    for contributor in contributors:
        set_index = _find_partner(context, contributor)
        if set_index is None:
            set_index = context.compute_next_set_index(CONTRIBUTOR_NAME)
            context.add(CONTRIBUTOR_NAME, contributor.name, set_index=set_index, dataset=False)
        _add_missing_partner_value(context, 'project/partner/given_name', contributor.given_name, set_index)
        _add_missing_partner_value(context, 'project/partner/family_name', contributor.family_name, set_index)
        if contributor.affiliations:
            _add_missing_partner_value(
                context,
                'project/partner/organization',
                contributor.affiliations[0].name,
                set_index,
            )
            if len(contributor.affiliations) > 1:
                context.warn('contributors.affiliation', 'Only the first contributor affiliation was imported')
            if contributor.affiliations[0].identifier or contributor.affiliations[0].scheme_uri:
                context.warn('contributors.affiliation',
                             'Only affiliation names have an established RDMO import destination')
        if contributor.identifiers:
            identifier = contributor.identifiers[0]
            if identifier.identifier_type == 'ORCID':
                _add_missing_partner_value(context, 'project/partner/orcid', identifier.value, set_index)
            else:
                context.warn('contributors', 'Only ORCID has a confirmed project-partner mapping', identifier.value)
            if len(contributor.identifiers) > 1:
                context.warn('contributors.nameIdentifier', 'Only the first contributor identifier was imported')
        if contributor.contributor_type not in (None, 'Other'):
            context.warn(
                'contributors',
                'Contributor role has no confirmed project-partner mapping',
                contributor.contributor_type,
            )


def _name_paths(base):
    return tuple(f'{base}/{field}' for field in ('name', 'given_name', 'family_name'))


def _report_orphan_identities(context, base, target):
    paths = tuple(f'{base}/{field}' for field in ('orcid', 'ror', 'name_identifier', 'person_or_entity', 'role'))
    anchors = (*_name_paths(base), f'{base}/orcid-autocomplete')
    claimed = set()
    for group in context.groups(*anchors):
        if any(value.text.strip() and value.option is None for path in anchors for value in group.get_values(path)):
            scoped = _descendant_context(context, group, anchors)
            claimed.update(id(value) for path in paths for value in scoped.get_values(path))
    sources = [value for path in paths for value in context.get_values(path)
               if value.is_true and id(value) not in claimed]
    if sources:
        context.warn(target, f'{base}/name', 'Identifier/type-only entries do not establish an entity name')
        context.record_mapping(target, sources=sources, outcome='rejected', reason='Missing entity name')


def _read_name(context, base, target):
    start = len(context.provenance) if context.provenance is not None else 0
    person = read_named_value(context, f'{base}/name', target=target)
    autocomplete = read_named_value(context, f'{base}/orcid-autocomplete', target=target, scheme='ORCID')
    name = person.name if person else None
    identifiers = list(person.identifiers) if person else []
    if autocomplete:
        identifiers.extend(autocomplete.identifiers)
        name = name or autocomplete.name
    given_name = context.get_text(f'{base}/given_name', target=f'{target}.given_name')
    family_name = context.get_text(f'{base}/family_name', target=f'{target}.family_name')
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


def _read_person_or_organization(context, base, target, *, parent):
    context = _descendant_context(parent, context, (*_name_paths(base), f'{base}/orcid-autocomplete'))
    name, given_name, family_name, identifiers = _read_name(context, base, target)
    if not name:
        if context.get_scope_values():
            context.warn(target, f'{base}/name', 'Identifier/type-only entries do not establish an entity name')
        return None
    identifiers = _read_identifiers(context, base, target, identifiers)
    if base == 'project/contributor':
        name_type = read_controlled_value(
            context, f'{base}/person_or_entity',
            {'partner-types/person': 'Personal', 'partner-types/entity': 'Organizational'},
            target=f'{target}.name_type',
        )
    else:
        name_type = read_controlled_value(context, f'{base}/name_type', XMLVocabulary.name_type_options,
                                          target=f'{target}.name_type')
    if name_type is None:
        schemes = {identifier.identifier_type for identifier in identifiers}
        name_type = 'Organizational' if 'ROR' in schemes else (
            'Personal' if given_name or family_name or 'ORCID' in schemes
            or base in ('project/partner', 'project/dataset/creator', 'project/dataset/owner') else None
        )
        if name_type:
            context.record_mapping(f'{target}.name_type', value=name_type, outcome='defaulted',
                                   reason='Identifier, structured name or established source category')
    elif ((name_type == 'Personal' and any(item.identifier_type == 'ROR' for item in identifiers))
          or (name_type == 'Organizational' and any(item.identifier_type == 'ORCID' for item in identifiers))):
        context.warn(target, f'{base}/name', 'Entity type conflicts with identifier; identity omitted')
        identifiers = []
    return PersonOrOrganization(
        name=name,
        given_name=given_name,
        family_name=family_name,
        name_type=name_type,
        identifiers=identifiers,
        affiliations=_read_affiliations(parent, context, base, target),
    )


def _read_identifiers(context, base, target, identifiers):
    evidence = []
    conflicting = False
    for path, hint in ((f'{base}/name', None), (f'{base}/orcid-autocomplete', 'ORCID')):
        for value in context.get_values(path):
            if value.option is not None:
                continue
            answer = normalize_answer(value.text, value.external_id, scheme=hint)
            if any('conflict' in issue.lower() for issue in answer.issues):
                conflicting = True
            if answer.identifier in identifiers:
                evidence.append((answer.identifier, (value,)))
    scheme_path = f'{base}/name_identifier_scheme'
    scheme = read_controlled_value(context, scheme_path, XMLVocabulary.name_identifier_scheme_options,
                                   target=f'{target}.identifiers[0].identifier_type')
    for path, expected in ((f'{base}/name_identifier', scheme), (f'{base}/orcid', 'ORCID'), (f'{base}/ror', 'ROR')):
        sources = context.get_values(path)
        value = context.get_identifier(path, target=f'{target}.identifiers[0].value')
        if not value:
            if any(value.external_id or value.text.strip() for value in sources):
                conflicting = True
            continue
        if not expected:
            context.warn(target, path, 'Identifier has no recognized scheme')
            conflicting = True
            continue
        detected = normalize_identifier(value)
        if detected and detected.identifier_type != expected:
            context.warn(target, path, 'Identifier scheme conflicts with its URI')
            conflicting = True
            continue
        identifier = normalize_identifier(value, expected) or Identifier(value, expected)
        if path.endswith('/name_identifier'):
            sources = [*sources, *context.get_values(scheme_path)]
        evidence.append((identifier, sources))
    by_scheme = {}
    for identifier, _ in evidence:
        by_scheme.setdefault(identifier.identifier_type, {})[identifier.value] = identifier
    if (conflicting or {'ROR', 'ORCID'} <= by_scheme.keys()
            or any(len(values) > 1 for values in by_scheme.values())):
        context.warn(target, f'{base}/name', 'Conflicting entity identifiers; identity omitted')
        return []
    result = [next(iter(values.values())) for values in by_scheme.values()]
    for index, identifier in enumerate(result):
        inputs = {id(value): value for item, values in evidence if item == identifier for value in values}
        sources = list(inputs.values())
        for field in ('value', 'identifier_type', 'scheme_uri'):
            value = getattr(identifier, field)
            if value is not None:
                context.record_mapping(f'{target}.identifiers[{index}].{field}', sources=sources,
                                       value=value, reason='Normalized entity identifier')
    return result


def _descendant_context(parent, group, anchors):
    """Read a person's nested affiliations without changing generic group semantics."""
    position = (*group.set_prefix.split('|'), str(group.set_index)) if group.set_prefix else (str(group.set_index),)
    placements = parent.prepared[1]
    ancestors = [placement for path in anchors if (key := parent.resolve_attribute(path)) is not None
                 for placement in placements.get(key, ()) if len(placement) == len(position)]

    def select(context, key):
        values = (parent.value_selector or select_values)(parent, key)
        related = [placement for placement in placements.get(key, ())
                   if any(placement[:len(position)] == ancestor for ancestor in ancestors)]
        if ancestors and placements.get(key) and not related:
            return []
        return [value for value in values if coordinates(value)[:len(position)] == position
                and (not related or any(matches_placement(value, placement) for placement in related))]

    return replace(group, value_selector=select)


def _read_affiliations(parent, context, base, target):
    if base == 'project/dataset/owner':
        path, id_path, scheme_path = (f'{base}/organization/name', f'{base}/organization/name/identifier/value',
                                     f'{base}/organization/name/identifier/type')
    elif base in ('project/partner', 'project/contributor'):
        path, id_path, scheme_path = f'{base}/organization', f'{base}/organization/ror', None
    else:
        path, id_path, scheme_path = f'{base}/affiliation', None, None
    scoped = _descendant_context(parent, context, (*_name_paths(base), f'{base}/orcid-autocomplete'))
    autocomplete_path = f'{path}/ror-autocomplete' if base == 'project/contributor' else None
    values = scoped.get_values(path)
    if autocomplete_path:
        values = [*values, *scoped.get_values(autocomplete_path)]
    affiliations = []
    groups = {(value.set_prefix, value.set_index) for value in values}
    for prefix, index in sorted(groups, key=lambda pair: (
        tuple(map(int, pair[0].split('|'))) if pair[0] else (), pair[1],
    )):
        group = _descendant_context(parent, parent.group(prefix, index),
                                    (path, autocomplete_path) if autocomplete_path else (path,))
        people = read_named_values(group, path, target=f'{target}.affiliations')
        # Provider-backed affiliation search is a separate sibling in SMP catalogs.
        if base == 'project/contributor':
            autocomplete = read_named_value(group, f'{path}/ror-autocomplete',
                                            target=f'{target}.affiliations[0]', scheme='ROR')
            if autocomplete:
                if not people:
                    people = [autocomplete]
                elif len(people) == 1:
                    people[0].identifiers.extend(autocomplete.identifiers)
        scheme = read_controlled_value(group, scheme_path, XMLVocabulary.name_identifier_scheme_options,
                                        target=f'{target}.affiliations[{len(affiliations)}].identifier_scheme'
                                        ) if scheme_path else 'ROR'
        raw_id = group.get_identifier(id_path) if id_path else None
        if raw_id and len(people) != 1:
            group.warn(target, id_path, 'Affiliation identifier is ambiguous across multiple names')
        for person in people:
            ids = list(person.identifiers)
            if raw_id and len(people) == 1:
                if scheme:
                    detected = normalize_identifier(raw_id)
                    if detected and detected.identifier_type != scheme:
                        group.warn(target, id_path, 'Affiliation identifier scheme conflicts with its URI')
                        ids = []
                    else:
                        ids.append(normalize_identifier(raw_id, scheme) or Identifier(raw_id, scheme))
                else:
                    group.warn(target, id_path, 'Affiliation identifier has no recognized scheme')
            identities = {(identifier.value, identifier.identifier_type) for identifier in ids}
            if len(identities) > 1 or any(identifier.identifier_type == 'ORCID' for identifier in ids):
                group.warn(target, path, 'Conflicting or non-organisational affiliation identifier')
                ids = []
            identifier = ids[0] if ids else None
            affiliation = Affiliation(person.name, identifier.value if identifier else None,
                                      identifier.identifier_type if identifier else None,
                                      identifier.scheme_uri if identifier else None)
            sources = [value for source in (path, id_path, scheme_path, f'{path}/ror-autocomplete') if source
                       for value in group.get_values(source)]
            for field in ('name', 'identifier', 'identifier_scheme', 'scheme_uri'):
                value = getattr(affiliation, field)
                if value is not None:
                    group.record_mapping(f'{target}.affiliations[{len(affiliations)}].{field}', sources=sources,
                                         value=value, reason='Creator-linked organisational affiliation')
            affiliations.append(affiliation)
    if len(affiliations) > 1:
        context.warn(target, path, 'RADAR accepts one affiliation; only the first is exported')
    return affiliations


def _read_role(context, base, target, *, parent):
    paths = (f'{base}/role', 'dmp/contributor/role') if base == 'project/contributor' else ()
    roles = []
    invalid = False
    for path in paths:
        # Literal aliases require catalog evidence, including scalar child questionsets.
        if path.startswith('dmp/'):
            role_key = context.resolve_attribute(path)
            placements = context.prepared[1]
            names = [placement for anchor in (*_name_paths(base), f'{base}/orcid-autocomplete')
                     if (key := context.resolve_attribute(anchor)) is not None
                     for placement in placements.get(key, ())]
            related = any(role[:len(name)] == name for role in placements.get(role_key, ()) for name in names)
            if role_key and not related:
                if parent.get_values(path):
                    context.warn(target, path, 'Contributor role alias has no shared catalog group')
                continue
        values = context.get_values(path)
        role = read_controlled_value(context, path, XMLVocabulary.contributor_type_options,
                                     target=f'{target}.contributor_type')
        if values and role is None:
            invalid = True
        if role:
            roles.append(role)
    if invalid or len(set(roles)) > 1:
        context.warn(target, paths[0], 'Unknown or conflicting contributor roles; Other retained')
    if not invalid and len(set(roles)) == 1:
        return roles[0]
    context.record_mapping(f'{target}.contributor_type', value='Other', outcome='defaulted',
                           reason='No single supported explicit contributor role')
    return 'Other'


def _find_partner(context: ProjectWriteContext, contributor: PersonOrOrganization) -> int | None:
    identifier = contributor.identifiers[0].value if contributor.identifiers else None
    if identifier:
        for value in context.get_values('project/partner/orcid'):
            if normalize(value.text) == normalize(identifier):
                return value.set_index
    for value in context.get_values(CONTRIBUTOR_NAME):
        if normalize(value.text) == normalize(contributor.name):
            return value.set_index
    return None


def _add_missing_partner_value(
    context: ProjectWriteContext,
    path: str,
    text: str | None,
    set_index: int,
) -> None:
    if text in (None, ''):
        return
    existing = [value for value in context.get_values(path) if value.set_index == set_index]
    if any(normalize(value.text) == normalize(text) for value in existing):
        return
    if existing:
        context.warn(path, 'Existing project value was preserved', text)
        return
    context.add(path, text, set_index=set_index, dataset=False)
