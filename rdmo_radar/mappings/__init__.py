"""Small callable mapping contracts, independent of Django and plugin registration."""
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExportCandidate:
    """A form key, label, and mapping-owned JSON scope captured before export."""
    key: str
    label: str
    scope: dict = field(default_factory=dict)
    radar_url: str | None = None
    fallback_file_stem: str | None = None


@dataclass(frozen=True)
class RadarMapping:
    """Interpret an RDMO project; imports and confirmed-result persistence are optional."""
    get_datasets: Callable
    build_reader: Callable
    compute_metadata: Callable
    build_import_writer: Callable | None = None
    store_result: Callable | None = None


def validate_candidates(candidates):
    """Reject ambiguous form keys or scopes that cannot survive the session round trip."""
    import json

    candidates = list(candidates)
    keys = set()
    for candidate in candidates:
        if not isinstance(candidate, ExportCandidate) or not isinstance(candidate.key, str) or not candidate.key:
            raise ValueError('RADAR mappings must return candidates with nonempty string keys.')
        if candidate.key in keys:
            raise ValueError('RADAR export candidate keys must be unique.')
        if (not isinstance(candidate.scope, dict) or
                json.loads(json.dumps(candidate.scope, allow_nan=False)) != candidate.scope):
            raise ValueError('RADAR export candidate scopes must contain JSON-compatible dictionaries and lists.')
        keys.add(candidate.key)
    return candidates
