"""Grouped funding references with explicit source selection."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..entities import normalized_answers, read_controlled_value
from ..normalization import normalize_answer, normalize_identifier
from ..types import FundingReference
from .contracts import AttributeSelector, GroupSpec
from .people import IdentifierSource


@dataclass(frozen=True)
class FundingSources:
    group: GroupSpec
    name: AttributeSelector
    scheme: AttributeSelector | None = None
    option_map: Mapping = field(default_factory=dict)
    award_number: AttributeSelector | None = None
    award_uri: AttributeSelector | None = None
    award_title: AttributeSelector | None = None
    identifier: IdentifierSource | None = None

    def __post_init__(self):
        object.__setattr__(self, 'option_map', MappingProxyType(dict(self.option_map)))


def read_funding(
    context, *, sources: FundingSources, target, normalizer=normalize_answer, identifier_normalizer=normalize_identifier
):
    references = []
    parent = sources.group.context(context)
    funders = parent.groups(*sources.group.anchors)
    for funder in funders:
        funder = parent.descendants(funder, sources.group.anchors)
        item_target = f'{target}[{len(references)}]'
        scheme_path = sources.scheme
        scheme = (
            read_controlled_value(
                funder,
                scheme_path,
                sources.option_map,
                target=f'{item_target}.funder_identifier.identifier_type',
            )
            if scheme_path
            else None
        )
        answers = list(
            normalized_answers(funder, sources.name, f'{item_target}.funder_name', scheme=scheme, normalizer=normalizer)
        )
        identities = {(answer.label, answer.identifier.value if answer.identifier else None) for _, answer in answers}
        name, identifier = None, None
        if len(identities) > 1:
            funder.warn(target, sources.name, 'Multiple answers for a scalar field')
            funder.record_mapping(
                f'{item_target}.funder_name',
                sources=[value for value, _ in answers],
                outcome='rejected',
                reason='Multiple funder answers',
            )
        elif answers:
            name, identifier = answers[0][1].label, answers[0][1].identifier
            input_values = [value for value, _ in answers]
            funder.record_mapping(
                f'{item_target}.funder_name', sources=input_values, value=name, reason='Normalized funder name'
            )
            if scheme_path and funder.get_values(scheme_path) and scheme is None:
                identifier = None
        else:
            funder.record_empty_mapping(f'{item_target}.funder_name', sources.name)
        identifier_inputs = [value for value, _ in answers]
        if sources.identifier is not None:
            spec = sources.identifier
            raw_id = funder.get_identifier(spec.value)
            if raw_id:
                identifier_inputs = [
                    *funder.get_values(spec.value),
                    *(funder.get_values(spec.scheme_source) if spec.scheme_source else ()),
                ]
                kind = (
                    read_controlled_value(
                        funder,
                        spec.scheme_source,
                        spec.option_map,
                        target=f'{item_target}.funder_identifier.identifier_type',
                    )
                    if spec.scheme_source
                    else spec.scheme
                )
                explicit = identifier_normalizer(raw_id, kind) if kind else None
                if explicit is None or (identifier is not None and explicit != identifier):
                    funder.warn(target, spec.value, 'Unknown or conflicting funder identifier')
                    identifier = None
                else:
                    identifier = explicit
        if identifier:
            for field in ('value', 'identifier_type', 'scheme_uri'):
                value = getattr(identifier, field)
                if value is not None:
                    funder.record_mapping(
                        f'{item_target}.funder_identifier.{field}',
                        sources=identifier_inputs,
                        value=value,
                        reason='Normalized funder identifier',
                    )
        reference = FundingReference(
            funder_name=name,
            funder_identifier=identifier,
            award_number=funder.get_text(sources.award_number, target=f'{item_target}.award_number')
            if sources.award_number
            else None,
            award_uri=funder.get_text(sources.award_uri, target=f'{item_target}.award_uri')
            if sources.award_uri
            else None,
            award_title=funder.get_text(sources.award_title, target=f'{item_target}.award_title')
            if sources.award_title
            else None,
        )
        if any((reference.funder_name, reference.award_number, reference.award_uri, reference.award_title)):
            if not reference.funder_name:
                reason = 'Funding reference has no funder name; complete it in RADAR'
                funder.warn(f'{item_target}.funder_name', sources.name, reason)
                evidence = [v for path in (sources.name, sources.award_number, sources.award_uri, sources.award_title)
                            if path is not None for v in funder.get_values(path)]
                funder.record_mapping(f'{item_target}.funder_name', sources=evidence, outcome='empty', reason=reason)
            references.append(reference)
    if not funders:
        context.record_empty_mapping(target, sources.name)
    return references
