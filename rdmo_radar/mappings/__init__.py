"""Small callable mapping contracts, independent of Django and plugin registration."""
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExportDataset:
    """RDMO answers selected to create one RADAR dataset.

    The key and label identify the dataset in the export form. The mapping-owned
    scope identifies its source answers and result destinations for callbacks.
    """
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


def validate_datasets(datasets):
    """Reject ambiguous form keys or scopes that cannot survive the session round trip."""
    import json

    datasets = list(datasets)
    keys = set()
    for dataset in datasets:
        if not isinstance(dataset, ExportDataset) or not isinstance(dataset.key, str) or not dataset.key:
            raise ValueError('RADAR mappings must return datasets with nonempty string keys.')
        if dataset.key in keys:
            raise ValueError('RADAR export dataset keys must be unique.')
        if (not isinstance(dataset.scope, dict) or
                json.loads(json.dumps(dataset.scope, allow_nan=False)) != dataset.scope):
            raise ValueError('RADAR export dataset scopes must contain JSON-compatible dictionaries and lists.')
        keys.add(dataset.key)
    return datasets
