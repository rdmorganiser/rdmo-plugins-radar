from .constants import XMLVocabulary
from .entities import normalized_answers, read_controlled_value
from .read_context import ProjectReadContext
from .types import FundingReference
from .values import normalize
from .write_context import ProjectWriteContext

FUNDER_ANCHOR = 'project/funder/id'
FUNDER_NAME = 'project/funder/name'


def read_funding(context: ProjectReadContext) -> list[FundingReference]:
    references = []
    funders = context.shared().groups(
        FUNDER_NAME, 'project/funder/grant_nr', 'project/funder/programme/title', 'project/funder/programme/url',
    )
    for funder in funders:
        target = f'funding_references[{len(references)}]'
        scheme_path = 'project/funder/id/type'
        scheme = read_controlled_value(
            funder, scheme_path, XMLVocabulary.funder_identifier_scheme_options,
            target=f'{target}.funder_identifier.identifier_type',
        )
        answers = list(normalized_answers(funder, FUNDER_NAME, f'{target}.funder_name', scheme=scheme))
        identities = {(answer.label, answer.identifier.value if answer.identifier else None) for _, answer in answers}
        name, identifier = None, None
        if len(identities) > 1:
            funder.warn('fundingReferences.funderName', FUNDER_NAME, 'Multiple answers for a scalar field')
            funder.record_mapping(f'{target}.funder_name', sources=[value for value, _ in answers],
                                  outcome='rejected', reason='Multiple funder answers')
        elif answers:
            name, identifier = answers[0][1].label, answers[0][1].identifier
            sources = [value for value, _ in answers]
            funder.record_mapping(f'{target}.funder_name', sources=sources, value=name, reason='Normalized funder name')
            if funder.get_values(scheme_path) and scheme is None:
                identifier = None
            if identifier:
                for field in ('value', 'identifier_type', 'scheme_uri'):
                    value = getattr(identifier, field)
                    if value is not None:
                        funder.record_mapping(f'{target}.funder_identifier.{field}', sources=sources,
                                              value=value, reason='Funder provider identifier')
        else:
            funder.record_empty_mapping(f'{target}.funder_name', FUNDER_NAME)
        reference = FundingReference(
            funder_name=name,
            funder_identifier=identifier,
            award_number=funder.get_text('project/funder/grant_nr', target=f'{target}.award_number'),
            award_uri=funder.get_text('project/funder/programme/url', target=f'{target}.award_uri'),
            award_title=funder.get_text('project/funder/programme/title', target=f'{target}.award_title'),
        )
        if any((reference.funder_name, reference.award_number, reference.award_uri, reference.award_title)):
            references.append(reference)
    if not funders:
        context.record_empty_mapping('funding_references', FUNDER_NAME)
    return references


def merge_funding(context: ProjectWriteContext, references: list[FundingReference]) -> None:
    for reference in references:
        set_index = _find_funder(context, reference)
        if set_index is None:
            set_index = context.compute_next_set_index(FUNDER_ANCHOR)
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
    context.add(path, text, set_index=set_index, dataset=False)
