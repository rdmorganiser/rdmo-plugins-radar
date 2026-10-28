"""Small, offline language vocabulary shared by TF readers and Option mappings.

Canonical codes follow RadarTypes.xsd (ISO 639-3). Bibliographic ISO 639-2/B
spellings such as ger/fre are accepted as inputs, never emitted.
"""
from unicodedata import normalize

# ISO 639-1, canonical RADAR code, accepted names and bibliographic aliases.
_LANGUAGES = (
    ('en', 'eng', ('English', 'Englisch')),
    ('de', 'deu', ('German', 'Deutsch', 'ger')),
    ('fr', 'fra', ('French', 'Französisch', 'Franzoesisch', 'Français', 'fre')),
    ('da', 'dan', ('Danish', 'Dänisch', 'Daenisch', 'Dansk')),
    ('nl', 'nld', ('Dutch', 'Niederländisch', 'Niederlaendisch', 'Nederlands', 'dut')),
    ('sv', 'swe', ('Swedish', 'Schwedisch', 'Svenska')),
    ('fi', 'fin', ('Finnish', 'Finnisch', 'Suomi')),
    ('it', 'ita', ('Italian', 'Italienisch', 'Italiano')),
    ('es', 'spa', ('Spanish', 'Spanisch', 'Español')),
    ('pt', 'por', ('Portuguese', 'Portugiesisch', 'Português')),
    ('pl', 'pol', ('Polish', 'Polnisch', 'Polski')),
    ('cs', 'ces', ('Czech', 'Tschechisch', 'Čeština', 'cze')),
)

LANGUAGE_OPTIONS = {f'language/{short}': code for short, code, _ in _LANGUAGES}
_ALIASES = {normalize('NFKC', name).casefold(): code
            for short, code, names in _LANGUAGES for name in (short, code, *names)}


def normalize_language(value: str) -> str | None:
    return _ALIASES.get(normalize('NFKC', value).strip().casefold())


def read_language(context, path='project/dataset/language') -> str | None:
    """Read one language from scoped text or identity-mapped Options.

Equivalent aliases agree; unknown answers or different languages require a
mapping correction instead of choosing an arbitrary scalar value.
"""
    selected = []
    for value in context.get_values(path):
        blank = value.option is None and not value.text.strip() and not value.external_id
        if value.is_true and not blank:
            selected.append(value)
        else:
            context.record_mapping('language', sources=(value,), outcome='skipped', reason='Answer is not selected')
    if not selected:
        context.record_empty_mapping('language', path)
        return None
    mapped = context.map_options(path, LANGUAGE_OPTIONS, values=selected)
    codes = {option if value.option is not None else normalize_language(value.text)
             for value, option in zip(selected, mapped, strict=True)}
    if None in codes or len(codes) > 1:
        reason = 'Unsupported or conflicting language answers'
        context.warn('language', path, reason)
        context.record_mapping('language', sources=selected, outcome='rejected', reason=reason)
        return None
    code = codes.pop()
    context.record_mapping('language', sources=selected, value=code, reason='Language vocabulary mapping')
    return code
