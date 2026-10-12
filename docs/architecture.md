# RADAR plugin architecture

The plugin uses RDMO 2's registered export/import interfaces, small factories, and services with explicit
callable dependencies. Metadata mapping and serialization have separate responsibilities. RDMO 3 frontend
integration is deferred; previous backend checks do not establish frontend support.

## Responsibilities

| Module | Responsibility |
|---|---|
| `exports/exports.py` | XML warnings, download confirmation, and ZIP responses. |
| `exports/providers.py`, `exports/credentials.py` | Forms, sessions, OAuth or credentials requests, and result presentation. |
| `imports/imports.py` | File checks, existing-project requirement, and RDMO import staging integration. |
| `factories.py` | Assemble defaults and prepare operation-scoped project data. |
| `services.py` | Prepare REST payloads, generate XML files, and coordinate parsing with import mapping. |
| `metadata/builder.py`, `metadata/importer.py` | Compose independently replaceable read/write mappings. |
| `metadata/dataset.py`, `metadata/people.py`, `metadata/funding.py` | Map their respective metadata fields. |
| `metadata/values.py`, `metadata/rdmo.py` | Prepare native Values/catalog placements, select scopes, and collect mapping issues. |
| `metadata/api.py`, `metadata/xml.py` | Convert canonical metadata to the RADAR REST/XML contracts and parse XML. |
| `client.py` | Credentials HTTP requests, RADAR response interpretation, and shared URL construction. |
| `exports/storage.py` | Atomically persist a confirmed RADAR ID and complete URL. |
| `exceptions.py` | Protocol, confirmed-result storage, and XML generation errors. |

Registered paths remain `rdmo_radar.exports.RadarExport`, `RadarExportProvider`,
`RadarCredentialsExportProvider`, and `rdmo_radar.imports.RadarImport`.

## Request flows

**XML export:** RDMO dispatches the registered plugin with a project or snapshot. The adapter resolves
`snapshot.project` when necessary, prepares the XML service, and converts its file results into translated
warnings or a ZIP. Missing metadata, mapping issues, and schema violations allow an explicit download.
Generation failures produce a safe error response. Filename sanitization and collision handling belong to
`RadarXmlExportService`; labels, templates, and responses belong to the adapter.

**Credentials export:** the adapter validates the form, prepares a payload through `RadarExportService`,
and creates the dataset through `RadarClient`. After RADAR confirms the ID, it constructs the human-facing
URL from that same client's base URL and the request language, then calls `service.store_result`.
Credentials are not stored; the bearer token belongs to the export session.

**OAuth export:** RDMO's `OauthProviderMixin` owns authorization, HTTP requests, and callback replay.
Before creation the adapter saves project ID, dataset index, actual RADAR base URL, and language in a
JSON-compatible `export_context`. The reconstructed callback binds its request for core hooks and resolves
the saved project. It calls `store_export_result` directly without constructing a service or loading Values.
Confirmed creation clears the saved operation context; cancellation clears it too.

**Import:** RDMO selects `RadarImport` using its file check. The import service parses XML and stages unsaved
Values through the supplied plugin's `get_attribute`, `get_option`, and `values` interfaces. RDMO owns preview
and saves only checked entries during apply. A new dataset index is allocated after the highest persisted
current dataset-title index. Shared contributor/funding fields are merged using prepared existing Values.

## Value access and operation lifetime

Factories load project Values once with `filter(snapshot=...).select_related('attribute', 'option')` and group
them by native `Attribute.path`. Catalog loading and recursive traversal reuse `Catalog.prefetch_elements()`,
`pages`, `descendants`, and `elements`. A small placement conversion retains outermost-first page/questionset
coordinates, repeated placements, non-collection zero coordinates, and empty collection markers.
Custom attribute URI prefixes are preserved because read mappings use model paths directly.

Component-wise scope matching keeps dataset indices `1` and `10` distinct and supports nested and shared
answers. The established catalog-less fallback remains. There is no separate answer tree or reader hierarchy.
`RDMOReadContext` provides path-based accessors, shared/group scopes, and diagnostics over prepared inputs;
it does not query the database or own a cache lifecycle. Import contexts resolve attributes/options through
RDMO's import API, including installed custom URI prefixes, and stage Values without saving them.

One service instance represents a prepared operation. Subsequent dataset reads add no Value queries and
select from attribute buckets. Each read gets a fresh diagnostic list; shared/group contexts within that
read share it. Export adapters rebuild their service when the project object, snapshot, or catalog changes.
For project edits, construct a new service. Preparation is not cached across requests.

## Service and mapping contracts

| Operation | Result |
|---|---|
| `compute_metadata(context, *, dataset, creators, contributors, funding)` | `MappingResult(metadata, issues)` |
| `write_metadata(plugin, metadata, set_index, *, existing_values, dataset, creators, contributors, funding)` | Tuple of mapping issues; Values are staged on the plugin. |
| `RadarExportService.compute_payload(set_index, responsible_email)` | `ExportPayload(payload, issues)`; no HTTP request or local write. |
| `RadarExportService.store_result(set_index, radar_id, radar_url)` | `ExportResult(radar_id, radar_url)` |
| `RadarXmlExportService.compute_files(indices)` | XML file results with completeness, schema, and mapping diagnostics. |
| `RadarImportService.process(root)` | Mapping issues returned by the configured writer. |

`RadarMetadata` contains descriptive metadata only. Result issue tuples capture diagnostics for that
operation; they are not mutable state on export instances. REST serialization adds explicit responsible
email and millisecond timestamp to the fixed RDDM 9.3 technical metadata. Missing draft titles get a fallback
without modifying the mapped metadata object. Frozen result dataclasses do not imply deep immutability.

## Extension examples

Factories supply defaults; named overrides replace only the supplied dependency. `None` means use the default.
They assemble Django/RDMO integration, while services can be constructed directly with supplied callables.

Default construction in an initialized RDMO environment:

```python
from rdmo_radar.factories import build_export_service, build_import_service, build_xml_export_service

export_service = build_export_service(project)
prepared = export_service.compute_payload(0, user.email)
xml_service = build_xml_export_service(project, snapshot=snapshot)
import_service = build_import_service(import_plugin)
```

Replace one mapping while keeping the others:

```python
from functools import partial

from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.types import Agent


def read_creators(context):
    return [Agent('Example University')]


mapping = partial(compute_metadata, creators=read_creators)
export_service = build_export_service(project, mapping=mapping)
xml_service = build_xml_export_service(project, mapping=mapping)
```

Import mappings use the same callable pattern, for example
`build_import_service(import_plugin, mapping=partial(write_metadata, funding=my_funding_writer))`.
The writer receives the mapping context and funding references and stages Values through that context.

Direct service construction with a supplied reader:

```python
from functools import partial

from rdmo_radar.services import RadarExportService
from rdmo_radar.metadata.api import compute_radar_payload
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.exports.storage import store_export_result

service = RadarExportService(
    reader=reader,
    mapping=compute_metadata,
    serializer=compute_radar_payload,
    writer=partial(store_export_result, project),
)
prepared = service.compute_payload(0, user.email)
```

The caller supplies the transport. The credentials adapter uses `RadarClient`; OAuth keeps RDMO's transport.
Both call `dataset_page_url(actual_base_url, confirmed_id, language)` and pass the resulting URL to persistence.
Direct services and canonical metadata remain importable without Django initialization. Mapping contexts are
imported explicitly from `rdmo_radar.metadata.rdmo`.

## Persistence and failures

`store_export_result(project, set_index, radar_id, radar_url)` stores the supplied complete URL unchanged.
It updates only the selected dataset's current flat Values (`snapshot=None`, `set_prefix=''`,
`collection_index=0`), skips missing installed target attributes, and writes ID/URL in one transaction.
The remote request occurs before that transaction. `ExportStoreError` retains the confirmed ID and URL.
If creation succeeds but the local write or callback project lookup fails, the adapter shows the confirmed
link without another export submission form. Successful storage redirects to that link.

`RadarClient.get` and `post` return native Requests responses, apply the configured timeout by default,
and propagate standard Requests transport/HTTP exceptions. Endpoint helpers additionally check JSON,
required token/ID fields, and workspace entries; invalid responses raise `RadarProtocolError`.
Adapters choose safe translated messages from status and workflow. Unconfirmed creation never stores a
result and warns users to check RADAR for a draft before retrying. Creation is never retried automatically.

## Verification and upstream gaps

Existing tests cover canonical XML/REST fixtures, dataset boundaries, custom URI prefixes, nested/repeated
placements, empty markers, snapshots, query reuse, callable replacement, diagnostics, import merging,
atomic persistence, and real RDMO 2 request/session/CSRF flows. Shared fixtures live in `tests/helpers.py`.
The known core `filter_set` index-boundary failure is an expected failure; plugin isolation tests pass.

Run the suite with `python -m pytest`, repository hooks with `pre-commit run --all-files`, and the standalone
benchmark with `python -m tests.benchmark_mapping`. The benchmark uses 2, 50, and 100 datasets and reports
query counts, timings, and metadata/diagnostic hashes. These retain 16 setup queries and zero subsequent
queries on the configured RDMO 2.5.2 fixture. The important query requirement is independence from dataset count.

Compatibility checks use released RDMO 2.5.1/2.5.2 and the pinned 2.6 source revision
`9f48c2fc93e021ff8eef3e087c1368235bef2e56`, with dependency versions reported explicitly.
The cleanup passes 250 tests with one expected upstream failure on each of those targets, using Python 3.14.7,
Django 5.2.18, DRF 3.18.3, and pytest 8.4.2. Metadata/diagnostic hashes and query counts match the pre-cleanup benchmark.
The earlier RDMO 3 backend check used revision `a14a08b74e91e75da9c79f0606ce6fdb5c86b64e`.
That source lacks the legacy project-export views and form template, so backend checks excluded the legacy
presentation cases. M7 readiness work and RDMO 3 frontend adapters are deferred.

Demonstrated upstream candidates:

- Boundary-safe `ValueQuerySet.filter_set`: prefix matching selects dataset `10` when requesting `1`.
  The minimized reproduction is retained in `tests/test_value_scopes.py`.
- A public catalog placement/scope helper covering repeated placements and empty page/questionset markers.
  The plugin currently performs only the conversion and scope matching described above.
- OAuth transport timeout/request hooks and safer core logging. The inspected core mixin does not expose
  these hooks and logs some upstream bodies itself; plugin-owned client error handlers log only status.

These are separate upstream tasks. See [metadata mapping](metadata-mapping.md) and
[the RADAR REST contract](radar-api-contract.md) for field semantics and API evidence.
