"""Offline normalization of supported provider answers; no RDMO or provider imports."""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from .types import Identifier

_PATTERNS = {
    'ROR': r'0[0-9a-z]{6}[0-9]{2}',
    'ORCID': r'[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9Xx]',
    'GND': r'(?:[0-9]+-[0-9Xx]|[0-9]{8,9}[0-9Xx])',
}
_HOSTS = {'ror.org': 'ROR', 'orcid.org': 'ORCID', 'd-nb.info': 'GND'}


def normalize_primary_identifier(value, scheme):
    """Normalize known resolver links and enforce the bundled identifierValue shape.

    No lookup or scheme inference is performed. The XSD requires two nonempty
    components separated by one slash; identifiers also cannot contain whitespace,
    control characters or display markup. Resolver queries/fragments are rejected.
    """
    value = (value or '').strip()
    if scheme not in ('DOI', 'Handle', 'RADAR'):
        return None
    # urlsplit removes embedded tabs/newlines; reject them before parsing too.
    if any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme:
            hosts = {'DOI': {'doi.org', 'dx.doi.org'}, 'Handle': {'hdl.handle.net'}}
            if (parsed.scheme.lower() not in ('http', 'https') or parsed.hostname not in hosts.get(scheme, ())
                    or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                    or parsed.port not in (None, 443 if parsed.scheme.lower() == 'https' else 80)):
                return None
            value = unquote(parsed.path[1:], errors='strict')
    except (ValueError, UnicodeError):
        return None
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        return None
    return value if re.fullmatch(r'[^/\s<>]+/[^/\s<>]+', value) else None


@dataclass(frozen=True)
class NormalizedAnswer:
    label: str
    identifier: Identifier | None = None
    issues: tuple[str, ...] = ()


def normalize_identifier(value, scheme=None):
    """Bare provider IDs require explicit context; URI namespaces identify themselves."""
    value = (value or '').strip()
    if not value or '<' in value or any(char.isspace() for char in value):
        return None
    try:
        parsed = urlsplit(value)
        detected = _HOSTS.get(parsed.hostname) if parsed.scheme in ('http', 'https') else None
    except ValueError:
        return None
    if detected:
        path = parsed.path.strip('/')
        if detected == 'GND':
            if not path.startswith('gnd/'):
                return None
            path = path[4:]
        if parsed.query or parsed.fragment or '/' in path or (scheme and scheme != detected):
            return None
        scheme, value = detected, path
    if scheme in _PATTERNS:
        if not re.fullmatch(_PATTERNS[scheme], value):
            return None
        if scheme == 'ROR':
            value = f'https://ror.org/{value}'
        elif scheme == 'GND':
            value = f'https://d-nb.info/gnd/{value.upper()}'
        else:
            value = value.upper()
    elif not scheme:
        return None
    return Identifier(value, scheme)


class _ProviderDisplay(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.href = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            if self.href:
                self.links.append(self.href)

    def handle_endtag(self, tag):
        if tag == 'a':
            self.href = None

    def handle_data(self, data):
        self.parts.append((data, self.href))


def normalize_answer(text, external_id='', *, scheme=None):
    """Extract labels from known ROR/ORCID/GND displays, retaining ordinary free text."""
    text = (text or '').strip()
    display = _ProviderDisplay(text)
    links = {href: normalized for href in display.links
             if (normalized := normalize_identifier(href)) is not None}
    candidates = {(item.value, item.identifier_type) for item in links.values()}
    issues = []
    identifier = None
    if len(candidates) > 1:
        issues.append('Conflicting provider identifiers')
    else:
        linked = next(iter(links.values()), None)
        hint = scheme or (linked.identifier_type if linked else None)
        if external_id:
            identifier = normalize_identifier(external_id, hint)
            if identifier is None:
                issues.append('Unsupported or malformed external identifier')
            elif linked and (identifier.value, identifier.identifier_type) not in candidates:
                issues.append('Conflicting provider identifiers')
                identifier = None
        elif linked:
            identifier = normalize_identifier(linked.value, scheme)
            if identifier is None:
                issues.append('Identifier scheme conflicts with provider identity')
        elif scheme and text:
            identifier = normalize_identifier(text, scheme)
    if links:
        label = ''.join(data for data, href in display.parts if href not in links).strip()
        if any(item.identifier_type == 'GND' for item in links.values()):
            label = label.replace('[]', '').split(' | ', 1)[0].strip()
        # A plain linked name is usable; a displayed URL/ID is not an entity name.
        if not label:
            label = ''.join(data for data, href in display.parts if href in links).strip()
            if any(label in (item.value, item.value.rsplit('/', 1)[-1], href)
                   for href, item in links.items()):
                label = ''
    else:
        label = text
    if identifier and normalize_identifier(label, identifier.identifier_type) == identifier:
        label = ''
    if identifier and not label:
        issues.append('Provider answer has no usable name or term label')
    return NormalizedAnswer(label, identifier, tuple(issues))
