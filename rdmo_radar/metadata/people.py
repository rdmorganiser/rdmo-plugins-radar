from .constants import XMLVocabulary
from .read_context import ProjectReadContext
from .types import Affiliation, Identifier, PersonOrOrganization
from .values import normalize
from .write_context import ProjectWriteContext

CREATOR_NAME = 'project/dataset/creator/name'
CONTRIBUTOR_NAME = 'project/partner/name'


def read_creators(context: ProjectReadContext) -> list[PersonOrOrganization]:
    creators = []
    groups = context.groups(CREATOR_NAME, 'project/dataset/creator/given_name', 'project/dataset/creator/family_name')
    for group in groups:
        creator = _read_person_or_organization(group, 'project/dataset/creator', f'creators[{len(creators)}]')
        if creator is not None:
            creators.append(creator)
    if not groups:
        context.record_empty_mapping('creators', CREATOR_NAME)
    return creators


def read_contributors(context: ProjectReadContext) -> list[PersonOrOrganization]:
    contributors = []
    groups = context.shared().groups(
        CONTRIBUTOR_NAME,
        'project/partner/given_name',
        'project/partner/family_name',
    )
    for group in groups:
        contributor = _read_partner(group, f'contributors[{len(contributors)}]')
        if contributor is not None:
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


def _read_name(context, base, target):
    start = len(context.provenance) if context.provenance is not None else 0
    name = context.get_text(f'{base}/name', target=f'{target}.name')
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
    return name, given_name, family_name


def _read_person_or_organization(context: ProjectReadContext, base: str, target: str) -> PersonOrOrganization | None:
    name, given_name, family_name = _read_name(context, base, target)
    if not name:
        return None
    identifier = context.get_identifier(f'{base}/name_identifier', target=f'{target}.identifiers[0].value')
    identifier_scheme = context.get_option(
        f'{base}/name_identifier_scheme',
        XMLVocabulary.name_identifier_scheme_options,
        target=f'{target}.identifiers[0].identifier_type',
    )
    affiliations = [
        Affiliation(name=value)
        for value in context.get_texts(
            f'{base}/affiliation',
            target=f'{target}.affiliations[{{index}}].name',
        )
    ]
    return PersonOrOrganization(
        name=name,
        given_name=given_name,
        family_name=family_name,
        name_type=context.get_option(
            f'{base}/name_type',
            XMLVocabulary.name_type_options,
            default='Personal',
            target=f'{target}.name_type',
        ),
        identifiers=[Identifier(identifier, identifier_scheme)] if identifier else [],
        affiliations=affiliations,
    )


def _read_partner(context: ProjectReadContext, target: str) -> PersonOrOrganization | None:
    name, given_name, family_name = _read_name(context, 'project/partner', target)
    if not name:
        return None
    identifier = context.get_identifier('project/partner/orcid', target=f'{target}.identifiers[0].value')
    organization = context.get_text('project/partner/organization', target=f'{target}.affiliations[0].name')
    context.record_mapping(
        f'{target}.name_type', value='Personal', outcome='defaulted', reason='Project partner category'
    )
    context.record_mapping(
        f'{target}.contributor_type', value='Other', outcome='defaulted', reason='Project partner role'
    )
    if identifier:
        context.record_mapping(
            f'{target}.identifiers[0].identifier_type',
            value='ORCID',
            outcome='defaulted',
            reason='Project partner identifier scheme',
        )
    return PersonOrOrganization(
        name=name,
        given_name=given_name,
        family_name=family_name,
        name_type='Personal',
        identifiers=[Identifier(identifier, 'ORCID')] if identifier else [],
        affiliations=[Affiliation(organization)] if organization else [],
        contributor_type='Other',
    )


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
