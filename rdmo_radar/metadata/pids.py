"""Offline PID schemes and detection, independent of RDMO and RADAR field policy."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar
from urllib.parse import urlsplit

from .types import Identifier


@dataclass(frozen=True)
class PIDScheme(ABC):
    """Subclass for an explicitly configured scheme; no global registration required.

    ``normalize`` accepts a bare ID or resolver URI and returns canonical metadata.
    Return None for invalid input. Custom schemes may populate Identifier.scheme_uri;
    the built-ins retain the established serializer-supplied URI defaults.
    """

    name: ClassVar[str]
    scheme_uri: ClassVar[str]
    resolver_hosts: ClassVar[tuple[str, ...]] = ()
    path_prefix: ClassVar[str] = ''
    pattern: ClassVar[str] = ''

    def recognizes_uri(self, value: str) -> bool:
        try:
            parsed = urlsplit(value)
            return parsed.scheme in ('http', 'https') and parsed.hostname in self.resolver_hosts
        except ValueError:
            return False

    def _local_id(self, value: str) -> str | None:
        value = (value or '').strip()
        if not value or '<' in value or any(char.isspace() or ord(char) < 32 for char in value):
            return None
        try:
            parsed = urlsplit(value)
            if parsed.scheme:
                if (not self.recognizes_uri(value) or parsed.username is not None or parsed.password is not None
                        or parsed.port not in (None, 443 if parsed.scheme == 'https' else 80)
                        or parsed.query or parsed.fragment):
                    return None
                value = parsed.path.strip('/')
                if not value.startswith(self.path_prefix):
                    return None
                value = value[len(self.path_prefix):]
        except ValueError:
            return None
        return value if re.fullmatch(self.pattern, value) else None

    @abstractmethod
    def normalize(self, value: str) -> Identifier | None:
        """Return the canonical identifier, without performing a remote lookup."""

    def as_uri(self, value: str) -> str | None:
        identifier = self.normalize(value)
        if identifier is None:
            return None
        return self.scheme_uri + identifier.value.rsplit('/', 1)[-1]


@dataclass(frozen=True)
class ORCIDScheme(PIDScheme):
    name = 'ORCID'
    scheme_uri = 'https://orcid.org/'
    resolver_hosts = ('orcid.org',)
    pattern = r'[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9Xx]'

    def normalize(self, value):
        local = self._local_id(value)
        return Identifier(local.upper(), self.name) if local else None


@dataclass(frozen=True)
class RORScheme(PIDScheme):
    name = 'ROR'
    scheme_uri = 'https://ror.org/'
    resolver_hosts = ('ror.org',)
    pattern = r'0[0-9a-z]{6}[0-9]{2}'

    def normalize(self, value):
        local = self._local_id(value)
        return Identifier(self.scheme_uri + local, self.name) if local else None


@dataclass(frozen=True)
class GNDScheme(PIDScheme):
    name = 'GND'
    scheme_uri = 'https://d-nb.info/gnd/'
    resolver_hosts = ('d-nb.info',)
    path_prefix = 'gnd/'
    pattern = r'(?:[0-9]+-[0-9Xx]|[0-9]{8,9}[0-9Xx])'

    def normalize(self, value):
        local = self._local_id(value)
        return Identifier(self.scheme_uri + local.upper(), self.name) if local else None


ORCID = ORCIDScheme()
ROR = RORScheme()
GND = GNDScheme()
BUILTIN_PID_SCHEMES = MappingProxyType({scheme.name: scheme for scheme in (ORCID, ROR, GND)})


def scheme_name(scheme: PIDScheme | str | None) -> str | None:
    return scheme.name if isinstance(scheme, PIDScheme) else scheme


def resolve_scheme(scheme: PIDScheme | str | None) -> PIDScheme | None:
    return scheme if isinstance(scheme, PIDScheme) else BUILTIN_PID_SCHEMES.get(scheme)


@dataclass(frozen=True)
class PIDMatch:
    scheme: PIDScheme
    identifier: Identifier
    start: int
    end: int


@dataclass(frozen=True)
class PIDDetection:
    matches: tuple[PIDMatch, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return len({(match.identifier.identifier_type, match.identifier.value) for match in self.matches}) > 1

    @property
    def identifier(self) -> Identifier | None:
        return self.matches[0].identifier if self.matches and not self.ambiguous else None


def detect_pid(text: str, *, schemes=None) -> PIDDetection:
    """Find validated resolver URLs with spans; bare IDs and namespace URIs do not match.

    Equivalent occurrences remain in matches for label extraction but represent one
    identity. Multiple different identities are ambiguous, never first-match wins.
    Pass an iterable of scheme objects to include custom schemes explicitly.
    """
    schemes = tuple(BUILTIN_PID_SCHEMES.values() if schemes is None else schemes)
    matches = []
    for token in re.finditer(r'https?://[^\s<>"\']+', text or '', flags=re.IGNORECASE):
        uri = token.group().rstrip('.,;:!?)]}')
        for scheme in schemes:
            if scheme.recognizes_uri(uri) and (identifier := scheme.normalize(uri)) is not None:
                matches.append(PIDMatch(scheme, identifier, token.start(), token.start() + len(uri)))
    return PIDDetection(tuple(matches))
