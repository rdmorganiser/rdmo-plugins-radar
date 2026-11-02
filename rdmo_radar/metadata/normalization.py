"""Offline normalization of supported provider answers; no RDMO or provider imports."""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from .pids import BUILTIN_PID_SCHEMES, PIDScheme, detect_pid, resolve_scheme, scheme_name
from .types import Identifier


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
        urlsplit(value)
    except ValueError:
        return None
    selected = resolve_scheme(scheme)
    if selected is not None:
        return selected.normalize(value)
    detected = next((item for item in BUILTIN_PID_SCHEMES.values() if item.recognizes_uri(value)), None)
    if detected:
        if scheme and scheme_name(scheme) != detected.name:
            return None
        return detected.normalize(value)
    # Preserve support for explicitly named local/other identifier schemes.
    return Identifier(value, scheme_name(scheme)) if scheme else None


@dataclass(frozen=True)
class IdentifierNormalization:
    identifier: Identifier | None
    issues: tuple[str, ...] = ()
    detected: bool = False


def normalize_source_identifier(value, scheme, *, detect_scheme=True, normalizer=normalize_identifier):
    """Normalize an explicit field while keeping custom callbacks string-based.

    Ambiguous detection and specific-scheme conflicts return diagnostic issues.
    Reader-level fallbacks for malformed typed values remain the caller's policy.
    """
    name = scheme_name(scheme)
    if detect_scheme:
        selected = resolve_scheme(scheme)
        schemes = (*BUILTIN_PID_SCHEMES.values(), selected) if selected else None
        detection = detect_pid(value, schemes=schemes)
        if detection.ambiguous:
            return IdentifierNormalization(None, ('Conflicting identifier URLs',))
        if detection.identifier:
            identifier = detection.identifier
            if name not in (None, 'Other', identifier.identifier_type):
                return IdentifierNormalization(None, ('Identifier scheme conflicts with its URI',))
            chosen = selected or resolve_scheme(identifier.identifier_type)
            result = normalizer(identifier.value, chosen if normalizer is normalize_identifier else chosen.name)
            return IdentifierNormalization(result, detected=result is not None)
    if not name:
        return IdentifierNormalization(None, ('Identifier has no recognized scheme',))
    # Detection can be disabled without disabling conflict checks on whole URIs.
    detected = normalizer(value)
    if detected and name not in ('Other', detected.identifier_type):
        return IdentifierNormalization(None, ('Identifier scheme conflicts with its URI',))
    return IdentifierNormalization(normalizer(value, scheme if normalizer is normalize_identifier else name))


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


def normalize_answer(text, external_id='', *, scheme=None, require_label=True):
    """Extract labels from known ROR/ORCID/GND displays, retaining ordinary free text."""
    text = (text or '').strip()
    display = _ProviderDisplay(text)
    schemes = tuple(BUILTIN_PID_SCHEMES.values())
    if isinstance(scheme, PIDScheme) and scheme.name not in BUILTIN_PID_SCHEMES:
        schemes += (scheme,)
    links = {href: detection.identifier for href in display.links
             if (detection := detect_pid(href, schemes=schemes)).identifier is not None}
    visible = ''.join(data for data, href in display.parts if href not in links)
    detection = detect_pid(visible, schemes=schemes)
    candidates = {(item.value, item.identifier_type): item for item in (
        *links.values(), *(match.identifier for match in detection.matches),
    )}
    issues = []
    identifier = None
    if len(candidates) > 1:
        issues.append('Conflicting provider identifiers')
    else:
        linked = next(iter(candidates.values()), None)
        specific = scheme if scheme_name(scheme) != 'Other' else None
        hint = specific or (linked.identifier_type if linked else scheme)
        if isinstance(scheme, PIDScheme) and linked and linked.identifier_type == scheme.name:
            hint = scheme
        if external_id:
            external = normalize_source_identifier(external_id, hint)
            identifier = external.identifier
            if identifier is None:
                if any('conflict' in issue.lower() for issue in external.issues):
                    issues.extend(external.issues)
                else:
                    issues.append('Unsupported or malformed external identifier')
            elif linked and (identifier.value, identifier.identifier_type) not in candidates:
                issues.append('Conflicting provider identifiers')
                identifier = None
        elif linked:
            identifier = normalize_identifier(linked.value, specific or resolve_scheme(linked.identifier_type))
            if isinstance(scheme, PIDScheme) and scheme.name == linked.identifier_type:
                identifier = scheme.normalize(linked.value)
            if identifier is None:
                issues.append('Identifier scheme conflicts with provider identity')
        elif specific and text:
            identifier = normalize_identifier(text, scheme)
    label = visible
    for start, end in sorted({(match.start, match.end) for match in detection.matches}, reverse=True):
        label = label[:start] + label[end:]
    if candidates:
        label = re.sub(r'\(\s*\)|\[\s*\]|\{\s*\}', '', label).strip(' \t\r\n,;:.!?')
        if any(item.identifier_type == 'GND' for item in candidates.values()):
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
    if identifier and not label and require_label:
        issues.append('Provider answer has no usable name or term label')
    return NormalizedAnswer(label, identifier, tuple(issues))
