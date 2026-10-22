"""Run with the configured interpreter: python -m tests.benchmark_mapping.

Uses an in-memory database and real DMP4NFDI answers. No RADAR network calls.
"""
import hashlib
import json
import os
from dataclasses import asdict
from statistics import median
from time import perf_counter

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.settings')

import django

django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from rdmo.core.xml import parse_xml_to_elements  # noqa: E402
from rdmo.management.imports import import_elements  # noqa: E402
from rdmo.projects.models import Project, Value  # noqa: E402
from rdmo.questions.models import Catalog  # noqa: E402

from .helpers import XML_DIRECTORY, export_for, make_prototype, read_metadata  # noqa: E402


def run_benchmark():
    call_command('migrate', verbosity=0)
    elements, errors = parse_xml_to_elements(XML_DIRECTORY / 'dmp4nfdi_v2-0-0.xml')
    assert not errors
    import_elements(elements)
    catalog = Catalog.objects.get(uri_path='dmp4nfdi/v2-0-0')
    source = make_prototype(catalog.pk)
    answers = list(source.values.select_related('attribute', 'option'))
    results = []
    for count in (2, 50, 100):
        project = Project.objects.create(title=f'{count} datasets', catalog_id=catalog.pk)
        copies = []
        for value in answers:
            path = value.attribute.path
            dataset = path.startswith('project/dataset/')
            if dataset and (value.set_prefix.split('|')[0] != '0' if value.set_prefix else value.set_index != 0):
                continue
            for index in range(count) if dataset else (None,):
                prefix = value.set_prefix
                set_index = value.set_index
                if dataset:
                    if prefix:
                        prefix = '|'.join((str(index), *prefix.split('|')[1:]))
                    else:
                        set_index = index
                copies.append(Value(
                    project=project, attribute=value.attribute, option=value.option, text=value.text,
                    external_id=value.external_id, value_type=value.value_type, set_prefix=prefix,
                    set_index=set_index, collection_index=value.collection_index,
                    created=value.created, updated=value.updated,
                ))
        Value.objects.bulk_create(copies)
        export = export_for(project)
        with CaptureQueriesContext(connection) as cold_queries:
            started = perf_counter()
            read_metadata(export, 0)
            cold_seconds = perf_counter() - started
        samples = []
        with CaptureQueriesContext(connection) as warm_queries:
            for _ in range(5):
                started = perf_counter()
                datasets = export.get_datasets()
                mapped = [read_metadata(export, dataset) for dataset in datasets]
                assert [dataset.key for dataset in datasets] == [str(index) for index in range(count)]
                samples.append(perf_counter() - started)
        metadata_data = [asdict(result.metadata) for result in mapped]
        issues_data = [[asdict(issue) for issue in result.issues] for result in mapped]
        wire = json.dumps(metadata_data, sort_keys=True).encode()
        issues_wire = json.dumps(issues_data, sort_keys=True).encode()
        results.append({
            'datasets': count, 'values': len(copies), 'cold_queries': len(cold_queries),
            'warm_queries': len(warm_queries), 'cold_seconds': round(cold_seconds, 6),
            'warm_median_seconds': round(median(samples), 6), 'metadata_sha256': hashlib.sha256(wire).hexdigest(),
            'issues_sha256': hashlib.sha256(issues_wire).hexdigest(),
        })
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    run_benchmark()
