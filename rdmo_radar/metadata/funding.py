from .rdmo import RDMOReadContext, RDMOWriteContext, normalize
from .types import FundingReference

FUNDER_ANCHOR = 'project/funder/id'
FUNDER_NAME = 'project/funder/name'


def read_funding(context: RDMOReadContext) -> list[FundingReference]:
    references = []
    funders = context.shared().groups(FUNDER_NAME, 'project/funder/grant_nr',
                                     'project/funder/programme/title', 'project/funder/programme/url')
    for funder in funders:
        references.append(FundingReference(
            funder_name=funder.get_text(FUNDER_NAME),
            award_number=funder.get_text('project/funder/grant_nr'),
            award_uri=funder.get_text('project/funder/programme/url'),
            award_title=funder.get_text('project/funder/programme/title'),
        ))
    return [reference for reference in references if any((
        reference.funder_name,
        reference.award_number,
        reference.award_uri,
        reference.award_title,
    ))]


def merge_funding(context: RDMOWriteContext, references: list[FundingReference]) -> None:
    for reference in references:
        set_index = _find_funder(context, reference)
        if set_index is None:
            set_index = context.next_set_index(FUNDER_ANCHOR)
            marker = reference.funder_name or reference.award_number or f'Funder {set_index + 1}'
            context.add(FUNDER_ANCHOR, marker, set_index=set_index, dataset=False)
            context.add(FUNDER_NAME, reference.funder_name, set_index=set_index, dataset=False)
        _add_missing(context, 'project/funder/grant_nr', reference.award_number, set_index)
        _add_missing(context, 'project/funder/programme/url', reference.award_uri, set_index)
        _add_missing(context, 'project/funder/programme/title', reference.award_title, set_index)
        if reference.funder_identifier:
            context.warn(
                'funderIdentifier',
                'No confirmed persistent funder identifier mapping; project/funder/id is only a set marker',
                reference.funder_identifier.value,
            )


def _find_funder(context: RDMOWriteContext, reference: FundingReference) -> int | None:
    if reference.funder_identifier:
        for value in context.values_for('project/funder/name_identifier'):
            if normalize(value.text) == normalize(reference.funder_identifier.value):
                return value.set_index
    if reference.funder_name:
        for value in context.values_for(FUNDER_NAME):
            if normalize(value.text) == normalize(reference.funder_name):
                return value.set_index
    return None


def _add_missing(context: RDMOWriteContext, path: str, text: str | None, set_index: int) -> None:
    if text in (None, ''):
        return
    existing = [value for value in context.values_for(path) if value.set_index == set_index]
    if any(normalize(value.text) == normalize(text) for value in existing):
        return
    if existing:
        context.warn(path, 'Existing project value was preserved', text)
        return
    context.add(path, text, set_index=set_index, dataset=False)
