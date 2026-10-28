"""Free text and GND keywords; terminology-service integration is deferred."""
from .constants import SCHEME_URIS
from .entities import normalized_answers
from .types import Keyword


def read_keywords(context):
    keywords, seen = [], set()
    for path, scheme in (
        ('project/research_question/keywords', None),
        ('project/research_question/keywords/gnd', 'GND'),
    ):
        for value, answer in normalized_answers(context, path, 'keywords', scheme=scheme):
            identifier = answer.identifier
            if identifier and identifier.identifier_type != 'GND':
                context.warn('keywords', path, 'Only GND keyword identifiers are supported')
                identifier = None
            identity = ('GND', identifier.value) if identifier else ('text', answer.label)
            if identity in seen:
                context.record_mapping('keywords', sources=(value,), outcome='skipped',
                                       reason='Duplicate normalized text' if not identifier else 'Duplicate GND term')
                continue
            seen.add(identity)
            # Keep untyped keywords as strings for existing mappings and callers.
            if identifier:
                keyword = Keyword(answer.label, 'GND', SCHEME_URIS['GND'], identifier.value,
                                  identifier.value.rsplit('/', 1)[-1])
                for field in ('value', 'keyword_scheme', 'scheme_uri', 'value_uri', 'classification_code'):
                    context.record_mapping(f'keywords[{len(keywords)}].{field}', sources=(value,),
                                           value=getattr(keyword, field), reason='GND provider keyword')
            else:
                keyword = answer.label
                context.record_mapping(f'keywords[{len(keywords)}]', sources=(value,), value=keyword,
                                       reason='Normalized text')
            keywords.append(keyword)
    if not keywords:
        context.record_empty_mapping('keywords', 'project/research_question/keywords')
    return keywords
