"""Single-source field getters; selectors and Option identities belong to profiles."""

from ..entities import read_named_values
from ..languages import normalize_language
from ..normalization import normalize_answer
from .contracts import Source


def read_text(context, *, source: Source, target, normalizer=str.strip):
    selected = source.context(context)
    text = selected.get_text(source.attribute, target=target)
    if text is None:
        return None
    result = normalizer(text)
    if result != text:
        selected.record_mapping(
            target,
            sources=selected.get_values(source.attribute),
            value=result,
            outcome='mapped' if result is not None else 'rejected',
            reason='Configured value normalization',
        )
    return result


def read_texts(context, *, source: Source, target, normalizer=str.strip):
    selected = source.context(context)
    texts = selected.get_texts(source.attribute, target=target)
    if normalizer is str.strip:
        return texts
    results = []
    for text in texts:
        normalized = normalizer(text)
        if normalized is not None and normalized not in results:
            index = len(results)
            selected.record_mapping(
                f'{target}[{index}]',
                sources=[value for value in selected.get_values(source.attribute) if value.text.strip() == text],
                value=normalized,
                reason='Configured value normalization',
            )
            results.append(normalized)
    return results


def read_option(context, *, source: Source, option_map, target):
    return source.context(context).get_option(source.attribute, option_map, target=target)


def read_names(context, *, source: Source, target, scheme=None, normalizer=normalize_answer):
    return read_named_values(
        source.context(context), source.attribute, target=target, scheme=scheme, normalizer=normalizer
    )


def read_language(context, *, source: Source, option_map, target, normalizer=normalize_language):
    selected = source.context(context)
    path = source.attribute
    values = []
    for value in selected.get_values(path):
        blank = value.option is None and not value.text.strip() and not value.external_id
        if value.is_true and not blank:
            values.append(value)
        else:
            selected.record_mapping(target, sources=(value,), outcome='skipped', reason='Answer is not selected')
    if not values:
        selected.record_empty_mapping(target, path)
        return None
    mapped = selected.map_options(path, option_map, values=values)
    codes = {
        option if value.option is not None else normalizer(value.text)
        for value, option in zip(values, mapped, strict=True)
    }
    if None in codes or len(codes) > 1:
        reason = 'Unsupported or conflicting language answers'
        selected.warn(target, path, reason)
        selected.record_mapping(target, sources=values, outcome='rejected', reason=reason)
        return None
    code = codes.pop()
    selected.record_mapping(target, sources=values, value=code, reason='Language vocabulary mapping')
    return code
