"""Template Framework import allocation and conservative merge policies."""

from ...metadata.types import FundingReference, PersonOrOrganization
from ...metadata.values import normalize
from ...metadata.write_context import ProjectWriteContext
from .vocabulary import XMLVocabulary

CREATOR_NAME = 'project/dataset/creator/name'
CONTRIBUTOR_NAME = 'project/partner/name'
FUNDER_ANCHOR = 'project/funder/id'
FUNDER_NAME = 'project/funder/name'


def write_creators(context: ProjectWriteContext, creators: list[PersonOrOrganization], *, target='creators') -> None:
    set_prefix = '|'.join(filter(None, (context.coordinates.set_prefix, str(context.coordinates.set_index))))
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
            if affiliation.has_identifier_metadata:
                context.warn(
                    'creators.affiliation', 'Only affiliation names have an established RDMO import destination'
                )


def merge_contributors(
    context: ProjectWriteContext, contributors: list[PersonOrOrganization], *, target='contributors'
) -> None:
    for contributor in contributors:
        set_index = _find_partner(context, contributor)
        if set_index is None:
            set_index = context.compute_next_set_index(CONTRIBUTOR_NAME)
            context.add(CONTRIBUTOR_NAME, contributor.name, set_index=set_index, set_prefix='')
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
            if contributor.affiliations[0].has_identifier_metadata:
                context.warn(
                    'contributors.affiliation', 'Only affiliation names have an established RDMO import destination'
                )
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
    context.add(path, text, set_index=set_index, set_prefix='')


def merge_funding(
    context: ProjectWriteContext, references: list[FundingReference], *, target='funding_references'
) -> None:
    for reference in references:
        set_index = _find_funder(context, reference)
        if set_index is None:
            set_index = context.compute_next_set_index(FUNDER_ANCHOR)
            marker = reference.funder_name or reference.award_number or f'Funder {set_index + 1}'
            context.add(FUNDER_ANCHOR, marker, set_index=set_index, set_prefix='')
            context.add(FUNDER_NAME, reference.funder_name, set_index=set_index, set_prefix='')
        _add_missing(context, 'project/funder/grant_nr', reference.award_number, set_index)
        _add_missing(context, 'project/funder/programme/url', reference.award_uri, set_index)
        _add_missing(context, 'project/funder/programme/title', reference.award_title, set_index)
        if reference.funder_identifier:
            context.warn(
                'funderIdentifier',
                'No confirmed persistent funder identifier mapping; project/funder/id is only a set marker',
                reference.funder_identifier.value,
            )


def _find_funder(context: ProjectWriteContext, reference: FundingReference) -> int | None:
    if reference.funder_identifier:
        for value in context.get_values('project/funder/name_identifier'):
            if normalize(value.text) == normalize(reference.funder_identifier.value):
                return value.set_index
    if reference.funder_name:
        for value in context.get_values(FUNDER_NAME):
            if normalize(value.text) == normalize(reference.funder_name):
                return value.set_index
    return None


def _add_missing(context: ProjectWriteContext, path: str, text: str | None, set_index: int) -> None:
    if text in (None, ''):
        return
    existing = [value for value in context.get_values(path) if value.set_index == set_index]
    if any(normalize(value.text) == normalize(text) for value in existing):
        return
    if existing:
        context.warn(path, 'Existing project value was preserved', text)
        return
    context.add(path, text, set_index=set_index, set_prefix='')
