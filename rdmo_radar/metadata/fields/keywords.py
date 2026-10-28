"""Free text and GND keywords; terminology-service integration is deferred."""

from ..constants import SCHEME_URIS
from ..entities import normalized_answers
from ..normalization import normalize_answer
from ..types import Keyword


def read_keywords(context, *, sources, target, normalizer=normalize_answer):
    keywords, seen = [], set()
    for source, scheme in sources:
        selected = source.context(context)
        path = source.attribute
        for value, answer in normalized_answers(selected, path, target, scheme=scheme, normalizer=normalizer):
            identifier = answer.identifier
            if identifier and identifier.identifier_type != 'GND':
                selected.warn(target, path, 'Only GND keyword identifiers are supported')
                identifier = None
            identity = ('GND', identifier.value) if identifier else ('text', answer.label)
            if identity in seen:
                selected.record_mapping(
                    target,
                    sources=(value,),
                    outcome='skipped',
                    reason='Duplicate normalized text' if not identifier else 'Duplicate GND term',
                )
                continue
            seen.add(identity)
            # Keep untyped keywords as strings for existing mappings and callers.
            if identifier:
                keyword = Keyword(
                    answer.label, 'GND', SCHEME_URIS['GND'], identifier.value, identifier.value.rsplit('/', 1)[-1]
                )
                for field in ('value', 'keyword_scheme', 'scheme_uri', 'value_uri', 'classification_code'):
                    selected.record_mapping(
                        f'{target}[{len(keywords)}].{field}',
                        sources=(value,),
                        value=getattr(keyword, field),
                        reason='GND provider keyword',
                    )
            else:
                keyword = answer.label
                selected.record_mapping(
                    f'{target}[{len(keywords)}]', sources=(value,), value=keyword, reason='Normalized text'
                )
            keywords.append(keyword)
    if not keywords:
        context.record_empty_mapping(target, sources[0][0].attribute)
    return keywords
