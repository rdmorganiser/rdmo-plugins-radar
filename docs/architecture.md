# RADAR values, mapping, and services: M0–M5 audit

These iterations keep registered XML, OAuth, credentials, and import adapters intact. M2 simplifies import
staging using the core lifecycle. M3 adds callable mapping composition and separates metadata from diagnostics.
M4 introduces independently tested services and M5 adds convenience factories; live adapters still use their
existing workflows. Live adapter delegation and RDMO 3 presentation adapters belong to later iterations.

## Starting point and core API evidence

Baseline: `b743855` on `dev-dmp4nfdi`, Python 3.14.7, RDMO 2.5.2, Django 5.2.18, pytest 8.4.2.
The existing 136 tests pass. Six additional black-box catalog/scoping tests pass against the original implementation.
The minimized `filter_set` boundary test fails as expected: selecting dataset `1` includes prefixes `1` and `10`.
The observed two-dataset fixture requires 16 cold queries and zero subsequent queries.

Audited installed sources and local core revisions: `9f48c2fc93e021ff8eef3e087c1368235bef2e56` (both the local
`2.5.1` tag and `rdmorganiser/2.6.0/release` reference), and `a14a08b74e91e75da9c79f0606ce6fdb5c86b64e`
(`rdmorganiser/3.0.0/release`). Branch names do not establish package versions; compatibility runs must print them.

| Existing responsibility | Reuse / keep / upstream decision |
|---|---|
| Loading native Values | Reuse `project.values.filter(snapshot=...).select_related('attribute', 'option')`; one query. |
| Attribute/option conversion | Reuse native `Attribute.path`, `Value.text`, `Value.is_true`, `Option.uri_path`, `external_id`. |
| Catalog loading/traversal | Reuse `Catalog.prefetch_elements()`, `Catalog.pages`, model `descendants` and `elements`. |
| Ancestry representation | Keep a small conversion of core preorder/model links to coordinate placements; core API gap. |
| Exact dataset/group scopes | Keep component-wise matching and established catalog-less fallback; core API gap. |
| Dataset discovery | Interpret native marker Values using placements, including markers without descendant questions. |
| Repeated reads | Operation-local dictionaries; scope selection never fetches Values or catalog data. |
| Mapping diagnostics | Keep scalar ambiguity, controlled-value and identifier rules in `RDMOReadContext`. |
| Import resolution/staging | Existing `Import.get_attribute/get_option/values` remains unchanged in M1. |

`Export.get_values/get_set` require an Export object and exact caller-supplied coordinates. Repeated per-field calls
would add queries. `ValueQuerySet.filter_set` needs a marker and uses unbounded `set_prefix__startswith`; it does not
cover shared fields, absent markers, or all valid placements. `compute_sets/distinct_list` on the 2.6 reference and
`compute_value_maps` on the 3.0 reference do not share a cross-version contract or supply catalog-aware scopes.

`ProjectWrapper.questions` is a useful public rendering representation, but `Question.to_dict` supplies full URIs
and immediate-parent-first ancestors, and the wrapper drops empty page/questionset containers. Combining it with
a second marker/ancestry implementation would increase complexity. Prefetched model Attributes provide paths
directly, including custom URI prefixes. Core `descendants` retains repeated occurrences and empty containers;
using its preorder avoids implementing another recursive catalog walker. Only coordinate-placement conversion
remains plugin-specific. It must preserve multiple placements and non-collection zero coordinates.

## Review gates

M0 characterization and this reuse matrix precede production changes. The M1 report must include full-suite and
version-specific results, metadata parity, cold/warm SQL counts and timing comparisons. Subsequent reads must add
zero Value queries. Removing `AnswerIndex` is an outcome of this simplification, not a reason to weaken parity.

Potential upstream work is a minimized, boundary-safe collection filter and a public catalog placement/scope
facility that includes page/questionset markers. Neither change is required in the installed core for this slice.

## M1 integration contract

`RDMOReadContext` takes prepared native Values grouped by attribute path, minimal placements, and a dataset index.
Each placement is an outermost-first tuple of `(attribute_path_or_none, is_collection)` for page/questionset
coordinates. Multiple placements of the same attribute remain distinct. These are operation-local data structures,
not a reader hierarchy or an independently maintained catalog tree. Attribute paths come from actual models;
there is no default-URI-prefix assumption or conversion through a rendering dictionary.

```python
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.rdmo import RDMOReadContext
from rdmo_radar.metadata.values import fetch_catalog_placements, fetch_project_values

values = fetch_project_values(project, snapshot)
placements = fetch_catalog_placements(project.catalog)
context = RDMOReadContext(values=values, placements=placements, set_index=10)
result = compute_metadata(context)
metadata = result.metadata
```

The context selects scopes, exposes mapping accessors, and collects issues. Shared/group contexts reuse inputs and
the same issue list. It holds no Export, Project, QuerySet, snapshot, or cache lifecycle. `compute_metadata` now
accepts this context directly; this is an intentional internal API change. Registered export/import class paths
and the adapters' metadata, title, dataset-choice, XML, OAuth, and credentials interfaces remain intact.

`RadarProjectExportBase.get_read_context` prepares inputs lazily and reuses them within that adapter instance.
Changing project, snapshot, or catalog invalidates preparation. Values remain a stable operation-local read;
in-operation edits are not a live-update mechanism. No metadata-result cache or process-wide cache is introduced.

`AnswerIndex`, `get_answer_index`, and the plugin's recursive `_walk` are removed. The small `metadata/values.py`
module remains because core has no complete coordinate-placement/scoping contract. It contains preparation and
stateless coordinate selection/discovery functions. It neither renders metadata nor saves Values. Lookup buckets
prevent scanning all project answers for each field; the existing scalar/group ordering and diagnostics remain.

## Validation results

All runs use Python 3.14.7, Django 5.2.18, and pytest 8.4.2. Source environments are independently installed from
archives of the audited commits; the build labels `2.6.0.dev0` and `3.0.0.dev0` were supplied explicitly because
the archives have no Git metadata. They identify source test targets, not released-package compatibility claims.

| Target | DRF | Result |
|---|---|---|
| PyPI RDMO 2.5.1 | 3.17.2 | 146 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 3.18.3 | 146 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 3.17.2 | 146 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, full suite | 3.18.3 | 145 passed, 1 legacy HTML failure, 1 expected upstream failure |
| Same RDMO 3.0 reference, backend suite | 3.18.3 | 145 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

The expected failure is **only** the minimized test of core `filter_set` leaking dataset `10` into dataset `1`.
Plugin isolation tests pass. That test accepts only assertion failures as expected; unrelated exceptions remain
failures. A core fix can make it pass without changing the plugin tests.

The pinned RDMO 3.0 `bootstrap_form` tag still renders `core/bootstrap_form.html`, but that template is absent from
both the source archive and installed package. The same HTML test fails on original RADAR commit `b743855`, so this
is a pre-existing presentation blocker. M1 does not supply a replacement template or dashboard integration.
`legacy_presentation` marks the retained HTML test. CI runs it on every 2.x target and explicitly excludes it from
the 3.0 **backend** job. This does not establish complete RDMO 3 UI support.

The compatibility matrix pins package versions/source commits and prints installed dependency versions. Repository
pre-commit checks, including ruff, pass both for all tracked files and the added test/benchmark files.

### Before/after measurements

`tests/benchmark_mapping.py` creates 2, 50, and 100 dataset projects from actual DMP4NFDI prototype answers in an
in-memory database. It measures first-dataset cold preparation and the median of five warm passes over every
dataset, including discovery. Baseline measurements used the original implementation before migration; final
measurements use M1 in the same configured environment. Times are local observations, not hard cross-version
ceilings. Very small timing differences should be treated as noise.

| Datasets | Values | Cold queries before/after | Warm queries before/after | Cold ms before/after | Warm ms before/after |
|---|---|---|---|---|---|
| 2 | 52 | 16 / 16 | 0 / 0 | 24.455 / 24.001 | 0.206 / 0.196 |
| 50 | 868 | 16 / 16 | 0 / 0 | 43.481 / 42.184 | 18.412 / 16.533 |
| 100 | 1718 | 16 / 16 | 0 / 0 | 70.811 / 71.052 | 62.302 / 62.383 |

Canonical metadata SHA-256 hashes match before/after for all three workloads:

| Datasets | SHA-256 |
|---|---|
| 2 | `70c3d1930a2509a684b5707b03c283cbd2f0d735c89cd54987facaa51770cba5` |
| 50 | `22ea775447088c8bbca2275669ac2d8d701f180803366d23e4ed04d289385480` |
| 100 | `95563f15781e73a813cf5edf2581945f7c53aec4d122c962440cced2a1b9f4cb` |

Tests separately assert exactly one initial Value query and zero additional queries for 2/50/100 datasets.
The existing snapshot/project switching, real observed RADAR XML/REST expectations, import staging, OAuth callback,
credentials, diagnostics, and escaping contracts remain active. New cases cover custom URI prefixes, empty
page/questionset markers, deep ancestry, reused questionsets, empty projects, and mapping without an Export.

M1 reached its review gate with these results. The remaining upstream candidates are exact scope/placement
operations, not a proposal to move a RADAR reader or RADAR-specific mapping rules into core.

## M2 import staging contract

The audited 2.x and 3.0 core `Import` implementations already preload installed objects, expose
`get_attribute(uri)` / `get_option(uri)`, and provide the `values` staging list. Core XML imports construct native
`Value` objects and append them directly; there is no public generic staging method to replace this operation.
The plugin continues to use that contract. It never inspects core's private lookup dictionaries and never calls
`Value.save()` or `save_import_values()` during mapping. RDMO's checked-value workflow owns persistence.

`RadarImport.process()` loads current project Values once through `fetch_project_values(project, snapshot=None)`
and passes the same prepared data to allocation and mapping. `compute_next_dataset_index(values)` preserves the
existing allocation rule: highest persisted dataset-title `set_index` plus one, or zero for an empty project.
Dataset ID markers, staged titles, and snapshot titles do not change this rule. Nested import-coordinate or
allocation-policy improvements are separate behavior changes.

`write_metadata(import_plugin, metadata, set_index, *, existing_values=None)` preserves the existing call shape.
When prepared data is omitted, it performs one current-project Value load; an explicitly supplied empty dictionary
is respected. `RDMOWriteContext(import_plugin, dataset_index, existing_values)` now requires prepared Values.
This is an intentional internal constructor change. The context groups persisted and already-staged Values once
by attribute path, copying the prepared lists so staging does not mutate the input. Its `_add_value` method is the
single construction/append path for text and options and updates the local grouping. `get_values` does no database
work; merge/allocation calculations inspect only the relevant attribute bucket. Staged changes must go through
the context during that operation; a later operation starts from the latest `Import.values` list.

Local helpers follow RDMO naming: `get_values`, `compute_next_set_index`, `compute_next_collection_index`,
`fetch_attribute`, and `fetch_option`. The latter two first call the core's public URI lookup methods, retaining
the existing default/alternative prefix precedence. Only the fallback for custom prefixes reads installed URIs
by attribute path or option URI path. Successful and missing resolutions are memoized within one context, avoiding
repeat queries without a plugin-wide cache or a separate writer framework.

The remaining plugin logic translates canonical RADAR fields, constructs their coordinates, and preserves
project-level values while merging. It does not duplicate the host's import persistence or URI dictionaries.
An upstream capability worth considering is public path-based import lookup with defined URI-prefix precedence;
the existing custom-prefix tests demonstrate that gap. A generic writer abstraction is not established by M2.

### M2 verification

`test_import_loads_values_once_and_preserves_project_data` runs with 1, 50, and 100 distinct contributor/funder
groups, including repeated incoming groups and conflicts against persisted data. Each import performs exactly
one SQL query during `process()` with installed standard URIs and an already-loaded project/catalog. Core plugin
initialization, which preloads attributes/options/tasks/views, is outside that measurement. Custom/missing URI
fallbacks cost at most one additional lookup per distinct attribute or option path per operation, not per group.

Tests also cover keyword normalization, persisted/staged deduplication, sparse set and collection indices,
creator prefixes (including dataset 10), controlled-option text and coordinates, unsaved Values, snapshot
exclusion, unchanged persisted project data, lookup precedence, resolution misses, and direct `write_metadata`
calls with or without prepared input. The existing real XML/REST, mapping, OAuth, and credentials tests remain.

| Target | M2 full-suite/backend result |
|---|---|
| PyPI RDMO 2.5.1 | 155 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 155 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 155 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 154 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

The expected upstream failure and the RDMO 3 HTML exclusion are the unchanged M1 limitations described above.
Repository pre-commit checks cover the changed production files, tests, and this audit.

M2 reached its review gate before mapping composition (M3).

## M3 mapping composition contract

`compute_metadata(context, *, dataset=read_dataset_fields, creators=read_creators,
contributors=read_contributors, funding=read_funding)` runs the existing functions in that order. Each reader
receives the same read context. The dataset reader supplies canonical metadata; the other readers supply their
corresponding lists. Any function can be replaced without subclassing or a mapping registry. Cohesive mapping
behavior remains in `dataset.py`, `people.py`, and `funding.py`.

The function and the export adapter's plugin-specific `compute_metadata` helper now return
`MappingResult(metadata: RadarMetadata, issues: tuple[MappingIssue, ...] = ())`. `RadarMetadata` no longer has a
`mapping_issues` field. All serializers and completeness checks still take canonical metadata alone. XML exports
and REST providers unwrap `.metadata` and consume `.issues` explicitly; prepared XML files retain their own issue
tuples. `RadarExport.get_dataset` no longer sets `self.mapping_issues`. Registered entry points and payload-returning
methods retain their contracts.

`write_metadata(import_plugin, metadata, set_index, *, existing_values=None,
dataset=write_dataset_fields, creators=write_creators, contributors=merge_contributors, funding=merge_funding)`
retains M2's preparation and unsaved Value staging. Dataset mapping receives the write context and all metadata;
the other writers receive the same context and their corresponding list. It returns only a diagnostic tuple,
not the consumed metadata. `RadarImport.mapping_issues` remains available for its logging/message lifecycle,
now as a tuple.

Both operations snapshot `context.issues` into a tuple. Later changes to the issue list do not alter that tuple.
The result dataclass is frozen, but its metadata and issue objects remain mutable; this is not deep immutability.
Contexts still belong to one mapping operation, with fresh issue lists for each dataset.

```python
from functools import partial

from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.importer import write_metadata

# my_creators(context) returns a list of Agents; all other readers retain their defaults.
mapping = partial(compute_metadata, creators=my_creators)
result = mapping(context)

# my_funding(context, references) stages through the supplied write context.
issues = write_metadata(plugin, result.metadata, set_index, existing_values=values, funding=my_funding)
```

These are deliberate internal API changes: metadata constructors no longer accept `mapping_issues`, export mapping
returns a result, and import mapping returns a tuple. There is no compatibility property forwarding metadata fields
or an additional import result type. The new result is exported by `rdmo_radar.metadata`.

### M3 verification

The focused composition tests replace each reader/writer independently, compare unchanged fields or staged Values,
check execution order and input identity, and verify unchanged import metadata. Diagnostic tests cover deduplication,
ordered snapshots, separate datasets, per-file warnings, and absence of hidden diagnostic state on XML exports.
Existing wire-format fixtures, schema validation, ZIP output, OAuth/credentials, URI aliases, snapshot selection,
coordinate boundaries, import staging, and query-count regressions retain their behavior contracts.

Before migration, the benchmark normalized M2 metadata and diagnostics into separate JSON arrays. M3 hashes the
same representation from the result objects. Both hashes match for 2, 50, and 100 datasets. This comparison accounts
for the intentional removal of the diagnostic field without hiding metadata or warning changes.

| Datasets | Cold queries before/after | Warm queries before/after | Cold ms before/after | Warm ms before/after |
|---|---|---|---|---|
| 2 | 16 / 16 | 0 / 0 | 128.768 / 37.220 | 0.199 / 0.196 |
| 50 | 16 / 16 | 0 / 0 | 44.585 / 55.328 | 18.352 / 23.758 |
| 100 | 16 / 16 | 0 / 0 | 85.801 / 66.611 | 71.788 / 61.537 |

These single local benchmark runs show timing variation; they are not evidence of a speedup. Query complexity,
normalized metadata, and diagnostic parity remain the acceptance criteria.

| Target | M3 result |
|---|---|
| PyPI RDMO 2.5.1 | 166 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 166 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 166 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 165 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

The core `filter_set` expected failure and RDMO 3 presentation limitation remain unchanged. Pre-commit checks
cover changed production files, migrated tests, the new composition tests, the benchmark, and this audit.

M3 reached its review gate before service composition (M4).

## M4 service contracts

M4 adds `rdmo_radar.services` and `exports/storage.py` without migrating registered plugin workflows. The
contracts below incorporate the M5 review adjustments. Dependencies are explicit callables; the service does
not own a client, settings, plugin instance, or value-reader class. Factory assembly belongs to M5 and live
adapter delegation belongs to M6. `RadarClient` now lives in top-level `client.py`; its RADAR endpoint behavior
remains unchanged.

`RadarExportService(reader, mapping, serializer, writer, *, clock=time.time)` exposes two independent operations:

1. `compute_payload(set_index, responsible_email)` reads and maps once, using M3's `MappingResult`. Missing titles
   use `Dataset #N` on a metadata copy, leaving the mapping result unchanged. Incomplete drafts remain valid
   candidates; the service does not impose publication completeness.
2. The serializer receives `responsible_email` and an integer millisecond `timestamp` from the clock. Pure
   `compute_radar_payload` retains retention period 10, RDDM 9.3, equal archive/publication times, and the existing
   REST descriptive serializer. It neither reads Django requests nor serializes through XML.
3. Preparation returns frozen `ExportPayload(payload, issues)` and performs neither HTTP requests nor writes.
   The payload and mapping diagnostics remain associated without mutable diagnostic state on the service.
4. `store_result(set_index, radar_id, radar_url)` calls `writer(set_index, radar_id, radar_url)` with the confirmed
   ID and complete URL supplied by the caller. It returns frozen `ExportResult(radar_id, radar_url)`; mapping
   diagnostics belong to the prepared payload. Storage does not repeat mapping or depend on preparation state.
5. A writer failure raises `ExportStoreError` retaining the confirmed ID, URL, and selected index, a safe public
   message, and the original exception chained for internal diagnosis. An existing `ExportStoreError` propagates
   unchanged, preserving its original cause rather than wrapping it again. No retry occurs.

The caller performs remote creation between these operations and supplies a confirmed ID and URL. Credentials
can call `RadarClient` explicitly; OAuth can retain RDMO's request and callback infrastructure. Neither workflow
is migrated in this iteration. There is no remote transaction, authentication workflow, or session state in the
service. The clock is replaceable for deterministic payload tests. These uncommitted API contracts are migrated
without deprecated wrappers because no external compatibility requirement has been established.

`RadarXmlExportService(reader, mapping, serializer, renderer, validator).compute_files(indices)` maps once per
dataset in supplied order. The renderer callable includes prettification. Filenames retain sanitization, the
180-character stem limit, numeric fallbacks, and case-insensitive collision suffixes. Titles come from mapped
metadata. Reader or mapper failures use the numeric fallback filename in `XmlExportError`; rendering failures
identify the computed filename. The safe error message does not include underlying exception text.

`XmlExportFile` contains `file_name`, `xml_data`, canonical missing-field paths, schema violation strings, mapping
issues, and a `validation_failed` flag. A validator exception preserves the generated XML and sets the flag;
later adapters must supply the existing translated warning. `has_warnings` considers each diagnostic category.
Translated labels, HTML confirmation, ZIP assembly, download handling, and Django responses remain outside the
service. No RADAR client or authentication dependency is needed for XML preparation.

`RadarImportService(parser, writer).process(root)` calls the parser and passes its metadata directly to the
configured writer, returning the writer's diagnostic tuple. The writer can be a `partial(write_metadata, ...)`.
File checking, project preparation, dataset allocation, logging/messages, and RDMO checked-value persistence
remain adapter responsibilities. This service introduces no import result wrapper and never saves staged Values.

### Confirmed-result storage

`store_export_result(project, set_index, radar_id, radar_url) -> None` writes available ID/URL attributes in one
local `transaction.atomic()` block. The complete supplied URL is stored unchanged: persistence does not read
provider settings or construct language-specific URLs. This prevents a custom transport's staging dataset from
being recorded with a production URL. It updates only live flat coordinates: `snapshot=None`, `set_prefix=''`,
selected `set_index`, and `collection_index=0`. Other projects, datasets, snapshots, nested prefixes, and
collection rows are unchanged. Missing installed attributes are skipped, matching the established behavior.
Failure on the URL write rolls back the preceding ID creation/update. The caller records results only after
confirmed remote creation; the storage operation does not open a transaction around HTTP calls. Direct calls
normalize the dataset index and raise the same `ExportStoreError` as service calls. The error is raised after the
transaction has rolled back, retaining the confirmed ID/URL and original exception without exposing database
details in the public message. Invalid index arguments fail during normalization before starting the write.

Direct persistence neither constructs a service nor prepares project Values/catalog information. This lets an
OAuth callback in a separate request store its confirmed result without eager mapping reads. The supplied
project and index identify the destination; no export context or previous service instance is required.

`dataset_page_url(radar_url, radar_id, language='en')` in `client.py` constructs the human-facing URL
from the actual instance used for creation. It removes trailing slashes and selects German for exact `de`,
otherwise English, preserving the existing ID interpolation. It does not read settings. The existing
`dataset_url()` API endpoint helper is unchanged. Storage persists the resulting complete URL unchanged.

These coordinate and transaction rules apply to the new helper. M4 deliberately leaves the old live
`complete_export` method unchanged; M6 will delegate to this boundary and handle confirmed-but-not-stored results
in presentation code.

### Direct construction

```python
from functools import partial

from rdmo_radar.client import dataset_page_url
from rdmo_radar.exports.storage import store_export_result
from rdmo_radar.metadata.api import compute_radar_payload
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.rdmo import RDMOReadContext
from rdmo_radar.metadata.values import fetch_catalog_placements, fetch_project_values
from rdmo_radar.services import RadarExportService

values = fetch_project_values(project, snapshot)
placements = fetch_catalog_placements(project.catalog)
reader = lambda index: RDMOReadContext(values, placements, set_index=index)
writer = partial(store_export_result, project)
service = RadarExportService(reader, compute_metadata, compute_radar_payload, writer)
prepared = service.compute_payload(0, responsible_email)
created = client.create_dataset(token, workspace_id, prepared.payload)
confirmed_url = dataset_page_url(client.radar_url, created['id'], language='de')
result = service.store_result(0, created['id'], confirmed_url)
issues = prepared.issues
```

A separate callback can store a confirmed result directly, without constructing either the service or factory:

```python
from rdmo_radar.client import dataset_page_url
from rdmo_radar.exports.storage import store_export_result

confirmed_url = dataset_page_url(oauth_radar_url, confirmed_id, language)
store_export_result(project, set_index, confirmed_id, confirmed_url)
```

Both entrypoints raise `ExportStoreError` on persistence failure. The registered callbacks will adopt this
boundary in M6; this iteration leaves their live workflow unchanged.

`client` is a configured existing `RadarClient` or a compatible fake. Preparing Values/catalog data remains outside
the service; replacing mapping, serialization, transport, or persistence requires no subclassing. Services do not
import the export adapter package, preventing circular dependencies when live delegation is added.

The metadata package previously eagerly imported RDMO contexts, indirectly requiring configured Django just to
import canonical metadata or services. Those three public context names now resolve lazily via module
`__getattr__`; their import paths remain available. Pure metadata, payload construction, and service operations
can run without Django initialization. This is import compatibility handling, not a dependency registry.

### M4 verification

The focused service/storage tests cover dependency arguments and ordering, title fallback without mutation,
draft preparation, millisecond payloads, preparation failures without writes, independent result storage,
confirmed-ID/URL retention after local failure, XML rendering/schema parity, safe filenames, validation failure
flags, and unsaved import staging. Storage tests cover unchanged complete URLs, missing attributes, exact
coordinate isolation, rollback on both new and existing rows, safe direct-call errors, unchanged error
propagation through the service, direct storage without preparation, shared dataset-page URL behavior, and
caller-owned remote creation outside the local write transaction. Existing client/provider tests retain transport failure and OAuth coverage.

A fresh subprocess removes `DJANGO_SETTINGS_MODULE`, executes all three services with fakes and the real pure
payload builder, and asserts Django, DRF, RDMO, and export adapters were not imported. A separate test verifies
the public lazy context imports still resolve to the original classes. Existing adapter behavior remains covered
by the full regression suite.

| Target | Original M4 result before M5 review adjustments |
|---|---|
| PyPI RDMO 2.5.1 | 201 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 201 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 201 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 200 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

Pre-commit checks pass for the new service/storage modules, pure payload builder, lazy metadata exports,
focused tests, and this audit. The upstream `filter_set` expected failure and RDMO 3 presentation limitation
remain unchanged.

M4 originally stopped for review before convenience factory assembly (M5).

## M5: convenience factories

`rdmo_radar.factories` assembles the three services with ordinary callable overrides. Only `None` selects a
default. No component registry, mapper class, or reader lifecycle is added, and direct service construction
remains supported. Registered export/import adapters continue using their existing implementation until M6.

Export factories eagerly prepare current or selected-snapshot Values and prefetched catalog placements when
no reader is supplied. Preparation loads Values in one query; subsequent dataset reads use the shared prepared
lookup dictionaries with fresh contexts and independent issue lists. These services represent one operation:
rebuild them after changing the project, snapshot, catalog, or answers.

```python
from functools import partial
from rdmo_radar.client import dataset_page_url
from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.metadata.builder import compute_metadata

mapping = partial(compute_metadata, creators=my_creators)
xml_service = build_xml_export_service(project, mapping=mapping)
files = xml_service.compute_files([0, 1])

export_service = build_export_service(project, mapping=mapping)
prepared = export_service.compute_payload(0, responsible_email)
created = my_client.create_dataset(token, workspace_id, prepared.payload)
confirmed_url = dataset_page_url(my_client.radar_url, created['id'])
result = export_service.store_result(0, created['id'], confirmed_url)
issues = prepared.issues
```

The REST defaults use `compute_radar_payload` and transactional `store_export_result`, binding only the
project to the writer. The factory does not construct a client or read `RADAR_PROVIDER`. Callers own transport
configuration and supply the confirmed complete URL. XML defaults use the existing renderer, core
`prettify_xml`, and schema validator. Neither export factory needs RADAR settings.

```python
from rdmo_radar.factories import build_import_service
from rdmo_radar.metadata.importer import write_metadata

mapping = partial(write_metadata, funding=my_funding_writer)
service = build_import_service(import_plugin, mapping=mapping)
issues = service.process(root)
```

Import preparation loads the existing project's current Values once, unless `existing_values` is supplied
(including an empty dictionary). The shared `compute_next_dataset_index` uses persisted dataset title indices
only, preserving the registered import adapter's allocation rule. An explicit index bypasses allocation.
Values remain staged, not saved. Supplied prepared Values must belong to the intended current project.
A custom writer replaces the complete staging operation and bypasses project preparation, index allocation,
and mapping assembly. The default preparation raises `ValueError` when there is no existing project; the
registered adapter's existing `ValidationError` behavior remains unchanged.

Factories assemble RDMO integration and may depend on initialized Django. Ordinary metadata/RDMO defaults are
imported at module scope. Export-package defaults remain local to avoid circular imports when registered
adapters later delegate to these factories. Django-free factory construction is not a requirement; pure services
remain directly constructible and independently tested without Django initialization.

M5 tests exercise default REST preparation/storage, XML output and schema parity, import allocation and staging,
callable replacement, falsey overrides, independence from provider settings, snapshot/project isolation,
prepared-data rebuilding, independent diagnostics, and one initial Value query with zero subsequent reads for
50 datasets.

| Target | M5 result before the final persistence/URL additions |
|---|---|
| PyPI RDMO 2.5.1 | 215 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 215 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 215 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 214 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

The adjusted count reflects removing the service's obsolete transport tests and factory initialization/client
requirements, while adding independent preparation/storage coverage. Existing client and registered adapter
regression tests remain active. Pre-commit checks and `git diff --check` pass.

M5 stops for review before migrating registered adapters in M6. The established upstream scoping failure and
RDMO 3 legacy presentation limitation remain unchanged.

The final persistence/URL additions retain the same M6 boundary: the credentials adapter will construct page
URLs from its client instance; OAuth will use its request instance and persist directly in the callback. Neither
live adapter is migrated here.

| Target | Final M5 result |
|---|---|
| PyPI RDMO 2.5.1 | 242 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 242 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 242 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 241 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

Direct persistence and service calls share safe errors without double wrapping. Tests verify direct storage
does not construct a service or prepare mapping data, and URL tests cover actual instances, trailing slashes,
language defaults, and preserved ID interpolation. Pre-commit checks and `git diff --check` pass.


## Initial pre-M6 cleanup: client structure and shared test helpers

`rdmo_radar/client.py` contains `RadarClient`, response interpretation, workspace parsing, and URL helpers.
The initial relocation preserved the existing client/service exception hierarchy and recognized-code logging;
the subsequent simplification below supersedes that error contract. `rdmo_radar/exceptions.py` now retains only
the protocol and export-operation errors. Repository imports and patch targets use these modules; the old
`exports/client.py` module has been removed. Registered RDMO plugin paths remain unchanged. The pure client,
exceptions, canonical metadata, and directly constructed services still work without Django initialization.

`RadarClient.get(url, *, token=None, **kwargs)` and its `post` counterpart return the original
`requests.Response`. They propagate standard Requests transport/HTTP errors and never retry, but accept
successful non-JSON and empty responses. The configured timeout is the default; explicit request timeouts
are forwarded unchanged. Supplied headers are preserved, with Bearer authorization overriding any existing
authorization case-insensitively when a token is provided. Caller header dictionaries are not mutated.

`authenticate`, `get_workspaces`, and `create_dataset` delegate through these methods, then use one private
JSON dictionary parser. Their public return types, token/ID checks, and workspace sorting remain unchanged.
HTTP classification now belongs to the presentation boundary rather than client exception subclasses. RDMO's OAuth request
and callback machinery is unchanged.

The existing completion method now calls `dataset_page_url` instead of duplicating its language-specific URL
construction. Full service/factory delegation and the reconstructed callback persistence changes remain M6.
No compatibility-only metadata exports or reader features are removed in this cleanup.

Shared `make_read_context`, `make_import`, and `export_for` test builders now live in `tests/helpers.py`.
`make_prototype(catalog_id)` holds ordinary project-loading logic used by both the fixture and benchmark;
the benchmark no longer imports a test module or calls a pytest fixture through `__wrapped__`. URL tests use
representative cases instead of the former Cartesian matrix.

Cleanup verification covers raw response identity, non-JSON/empty success, headers and timeout overrides,
raw HTTP and response-backed transport failures, endpoint delegation, preserved endpoint behavior, production
completion URLs, shared fixtures, and Django-free client/service construction. The temporary compatibility
environments were rebuilt using the configured SDK's Django 5.2.18, DRF 3.18.3, pytest 8.4.2, and Python 3.14.7
packages, with separately installed RDMO versions. Historical results above used their original environments.

| Target | Cleanup result |
|---|---|
| PyPI RDMO 2.5.1 | 232 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 232 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 232 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 231 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

The changed count combines the smaller URL case set with added raw HTTP contract tests. The extracted-helper
benchmark runs successfully for 2, 50, and 100 datasets, retaining 16 cold queries and zero warm queries.
Warm medians in this run were 0.204 ms, 16.609 ms, and 63.314 ms; these are observations rather than speedup claims.
Pre-commit checks and `git diff --check` pass. Cleanup stops for review before the checkpoint commit and M6.


## Pre-M6 cleanup: standard error handling

The client no longer accepts or threads an `operation` argument. Its shared request method sends the request,
calls `response.raise_for_status()`, and returns the response. Requests exceptions propagate unchanged,
including the response on `HTTPError` and original timeout/connection errors. Successful raw methods still
accept non-JSON/empty responses. Status handling follows standard Requests behavior without an extra bespoke
2xx check. Timeout defaults/overrides, header merging, and no automatic retries remain intact.

The custom client/request/authentication/authorization/metadata hierarchy, response classifier, recognized-code
allowlist, and exception-constructor logging have been removed. `RadarProtocolError` derives directly from
`Exception` with the fixed message `RADAR returned an invalid response.` and no status, code, or operation fields.
JSON dictionary validation, required token/ID checks, and basic workspace ID/title checks remain. Export storage
and XML-generation error contracts are unchanged.

Adapters catch `requests.RequestException` and `RadarProtocolError` and use presentation-stage context to choose
translated messages. Login HTTP 400/401 reports login failure; workspace/export 401 drops the token and returns
to credentials. Permission failures (403) and dataset metadata rejection (400/422) preserve the bound form and
token. Other dataset-creation failures warn that the export could not be confirmed and an existing draft should
be checked before retrying. Ordinary request failures receive a generic message. No unconfirmed result is saved.

The OAuth callback uses one generic authorization-failure message instead of parsing `invalid_client` and
`invalid_grant`. A callback request failure during a saved creation workflow also includes the unconfirmed-export
warning. RDMO's authorization state, request replay, token exchange, and transport behavior remain unchanged;
the saved session `operation` still identifies that workflow and is not a client argument. The core error-message
hook feeds a standard `HTTPError` carrying the response into the same presentation logic.

Plugin-owned handlers log only status and never display/log raw exception text or upstream bodies. There is no
client-side logging or exception sanitization wrapper; callers receive native Requests exceptions and adapters
show safe translated messages. RDMO core's own OAuth transport logging remains the upstream behavior documented
in README. Tests assert native exception propagation, adapter-safe messages/logging, token retention and expiry,
HTTP 400/401 login failures, 403/400/422/500 export outcomes, timeout, invalid JSON, missing IDs, and no retries.

| Target | Standard error-handling result |
|---|---|
| PyPI RDMO 2.5.1 | 234 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 234 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 234 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 233 passed, 1 legacy HTML test deselected, 1 expected upstream failure |

Pre-commit checks and `git diff --check` pass. Registered plugin interfaces, service/factory composition,
persistence, mapping, and benchmark logic remain unchanged. This cleanup stops for review before the checkpoint
commit and M6; no compatibility aliases retain the removed uncommitted error APIs.


## M6: registered adapters use the composed operations

This section describes the current implementation; the preceding milestone sections record earlier states.
The registered class paths in `rdmo_radar.exports` and `rdmo_radar.imports` remain unchanged.

- `RadarExport` prepares one XML service through `build_xml_export_service`, then turns its file results into
  translated template data or a ZIP response. RDMO's snapshot view supplies a snapshot without a project;
  the adapter resolves `snapshot.project` before preparing snapshot-scoped Values. Warnings, explicit download,
  safe filenames, schema failure warnings, and safe generation-error responses retain their existing behavior.
- Both direct providers use `build_export_service` for payload preparation. The credentials provider owns its
  `RadarClient` request. The same client instance supplies the actual RADAR base URL for the confirmed link.
  RDMO's OAuth mixin continues to own authorization, requests, and callback replay.
- Before OAuth creation, the adapter saves a JSON-compatible operation context containing project ID, dataset
  index, actual RADAR base URL, and language. A reconstructed callback binds the current request for core hooks,
  resolves the saved project, and calls `store_export_result` directly. It does not construct an export service
  or load project answers. Later form-session state cannot change the saved operation's destination.
- `store_export_result` stores the complete supplied URL unchanged and updates only current, flat Values with
  collection index zero. ID and URL writes are atomic. Confirmed remote creation with a missing project or failed
  local write displays the confirmed dataset link without another export submission form. Successful storage
  redirects to that link. Unconfirmed remote outcomes never write a result and retain the draft-check warning.
- `RadarImport` delegates parsing and mapping to `build_import_service`. Its check, existing-project requirement,
  mapping diagnostics, and RDMO preview/apply lifecycle remain in the adapter. Services stage unsaved Values;
  RDMO saves only the checked preview entries.

Each export adapter reuses its prepared service for the same project object, snapshot, and catalog. A changed
scope rebuilds it; preparation is not cached across requests. Mapping contexts remain fresh for every dataset.
The broad `RadarProjectExportBase`, adapter-local file/result dataclasses, and duplicate mapping, payload,
filename, persistence, and import-allocation implementations have been removed. The small direct-provider base
retains shared forms, session access, warnings, configuration, and presentation; OAuth uses core authorization
headers. No extra registry, cache framework, mapper class, or compatibility wrapper replaces the removed code.

Tests now mount the real RDMO host routes and settings, with authenticated Django clients and mocked RADAR HTTP.
They cover project permissions, CSRF, XML warnings/download, native snapshot dispatch, credentials forms/errors,
current-versus-snapshot storage, rollback after confirmed creation, reconstructed OAuth callback success and
failure, saved destination isolation, actual client URLs/language, and import upload/preview/checked apply.
Host tests restore language after requests so their locale selection does not affect later mapping tests.
RDMO 3 reference sources lack the legacy project-export views/templates; these presentation tests are explicitly
excluded from that backend compatibility run. The exclusion is not a claim of RDMO 3 frontend compatibility.

The 2/50/100-dataset benchmark preserves the pre-M6 metadata and diagnostic hashes, 16 cold queries, and zero
warm queries. Warm medians observed during this run were 0.227 ms, 20.653 ms, and 72.329 ms; timings are
observations rather than a speedup claim. M6 stops for review before M7; changes remain uncommitted.

| Target | M6 result |
|---|---|
| PyPI RDMO 2.5.1 | 252 passed, 1 expected upstream failure |
| Configured RDMO 2.5.2 | 252 passed, 1 expected upstream failure |
| RDMO 2.6 reference `9f48c2f` | 252 passed, 1 expected upstream failure |
| RDMO 3.0 reference `a14a08b`, backend suite | 233 passed, 19 legacy presentation cases deselected, 1 expected upstream failure |
