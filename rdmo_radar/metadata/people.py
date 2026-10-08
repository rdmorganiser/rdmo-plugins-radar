from .constants import XMLVocabulary
from .rdmo import RDMOReadContext, RDMOWriteContext, normalize
from .types import Affiliation, Agent, Identifier

CREATOR_NAME = 'project/dataset/creator/name'
CONTRIBUTOR_NAME = 'project/partner/name'


def read_creators(context: RDMOReadContext) -> list[Agent]:
    return [agent for group in context.groups(CREATOR_NAME, 'project/dataset/creator/given_name',
                                              'project/dataset/creator/family_name')
            if (agent := _read_agent(group, 'project/dataset/creator')) is not None]


def read_contributors(context: RDMOReadContext) -> list[Agent]:
    return [agent for group in context.shared().groups(CONTRIBUTOR_NAME, 'project/partner/given_name',
                                                       'project/partner/family_name')
            if (agent := _read_partner(group)) is not None]


def write_creators(context: RDMOWriteContext, creators: list[Agent]) -> None:
    prefix = str(context.dataset_index)
    for index, creator in enumerate(creators):
        context.add(CREATOR_NAME, creator.name, set_prefix=prefix, set_index=index)
        context.add('project/dataset/creator/given_name', creator.given_name, set_prefix=prefix, set_index=index)
        context.add('project/dataset/creator/family_name', creator.family_name, set_prefix=prefix, set_index=index)
        context.add_option(
            'project/dataset/creator/name_type',
            creator.name_type,
            XMLVocabulary.name_type_options,
            set_prefix=prefix,
            set_index=index,
        )
        if creator.identifiers:
            identifier = creator.identifiers[0]
            context.add(
                'project/dataset/creator/name_identifier',
                identifier.value,
                set_prefix=prefix,
                set_index=index,
            )
            context.add_option(
                'project/dataset/creator/name_identifier_scheme',
                identifier.identifier_type,
                XMLVocabulary.name_identifier_scheme_options,
                set_prefix=prefix,
                set_index=index,
            )
            if len(creator.identifiers) > 1:
                context.warn('creators.nameIdentifier', 'Only the first creator identifier was imported')
        if creator.affiliations:
            affiliation = creator.affiliations[0]
            context.add(
                'project/dataset/creator/affiliation',
                affiliation.name,
                set_prefix=prefix,
                set_index=index,
            )
            if len(creator.affiliations) > 1:
                context.warn('creators.affiliation', 'Only the first creator affiliation was imported')


def merge_contributors(context: RDMOWriteContext, contributors: list[Agent]) -> None:
    for contributor in contributors:
        set_index = _find_partner(context, contributor)
        if set_index is None:
            set_index = context.next_set_index(CONTRIBUTOR_NAME)
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


def _read_agent(context: RDMOReadContext, base: str) -> Agent | None:
    name = context.get_text(f'{base}/name')
    given_name = context.get_text(f'{base}/given_name')
    family_name = context.get_text(f'{base}/family_name')
    if not name:
        name = ', '.join(value for value in (family_name, given_name) if value)
    if not name:
        return None
    identifier = context.get_identifier(f'{base}/name_identifier')
    identifier_scheme = context.get_option(
        f'{base}/name_identifier_scheme',
        XMLVocabulary.name_identifier_scheme_options,
    )
    affiliations = [Affiliation(name=value) for value in context.get_texts(f'{base}/affiliation')]
    return Agent(
        name=name,
        given_name=given_name,
        family_name=family_name,
        name_type=context.get_option(
            f'{base}/name_type',
            XMLVocabulary.name_type_options,
            default='Personal',
        ),
        identifiers=[Identifier(identifier, identifier_scheme)] if identifier else [],
        affiliations=affiliations,
    )


def _read_partner(context: RDMOReadContext) -> Agent | None:
    name = context.get_text(CONTRIBUTOR_NAME)
    given_name = context.get_text('project/partner/given_name')
    family_name = context.get_text('project/partner/family_name')
    if not name:
        name = ', '.join(value for value in (family_name, given_name) if value)
    if not name:
        return None
    identifier = context.get_identifier('project/partner/orcid')
    organization = context.get_text('project/partner/organization')
    return Agent(
        name=name,
        given_name=given_name,
        family_name=family_name,
        name_type='Personal',
        identifiers=[Identifier(identifier, 'ORCID')] if identifier else [],
        affiliations=[Affiliation(organization)] if organization else [],
        contributor_type='Other',
    )


def _find_partner(context: RDMOWriteContext, contributor: Agent) -> int | None:
    identifier = contributor.identifiers[0].value if contributor.identifiers else None
    if identifier:
        for value in context.values_for('project/partner/orcid'):
            if normalize(value.text) == normalize(identifier):
                return value.set_index
    for value in context.values_for(CONTRIBUTOR_NAME):
        if normalize(value.text) == normalize(contributor.name):
            return value.set_index
    return None


def _add_missing_partner_value(
    context: RDMOWriteContext,
    path: str,
    text: str | None,
    set_index: int,
) -> None:
    if text in (None, ''):
        return
    existing = [value for value in context.values_for(path) if value.set_index == set_index]
    if any(normalize(value.text) == normalize(text) for value in existing):
        return
    if existing:
        context.warn(path, 'Existing project value was preserved', text)
        return
    context.add(path, text, set_index=set_index, dataset=False)
