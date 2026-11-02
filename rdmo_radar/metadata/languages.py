"""Small, offline language vocabulary independent of Attribute and Option selection.

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

LANGUAGE_CODES = {short: code for short, code, _ in _LANGUAGES}
_ALIASES = {normalize('NFKC', name).casefold(): code
            for short, code, names in _LANGUAGES for name in (short, code, *names)}


def normalize_language(value: str) -> str | None:
    return _ALIASES.get(normalize('NFKC', value).strip().casefold())
