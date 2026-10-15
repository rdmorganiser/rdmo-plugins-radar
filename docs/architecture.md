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
| `mappings/__init__.py` | Frozen callable profiles and export datasets; no Django dependency. |
| `mappings/project.py` | One conservative project-level record, with optional custom metadata functions. |
| `mappings/template_framework.py` | TF discovery, complete dataset coordinates, import allocation, and result destinations. |
| `services.py` | Prepare REST payloads, generate XML files, and coordinate parsing with import mapping. |
| `metadata/builder.py`, `metadata/importer.py` | Compose independently replaceable read/write mappings. |
| `metadata/dataset.py`, `metadata/people.py`, `metadata/funding.py` | Map their respective metadata fields. |
| `metadata/values.py` | Prepare native Values/catalog placements, match coordinates, and provide shared answer helpers. |
| `metadata/read_context.py` | Scoped project Value access and mapping diagnostics through `ProjectReadContext`. |
| `metadata/write_context.py` | Resolve import destinations, merge answers, and stage unsaved Values through `ProjectWriteContext`. |
| `metadata/api.py`, `metadata/xml.py` | Convert canonical metadata to the RADAR REST/XML contracts and parse XML. |
| `client.py` | Credentials HTTP requests, RADAR response interpretation, and shared URL construction. |
| `exports/storage.py` | Atomically persist a confirmed RADAR ID and complete URL. |
| `exceptions.py` | Protocol, confirmed-result storage, and XML generation errors. |

Existing paths `rdmo_radar.exports.RadarExport`, `RadarExportProvider`, `RadarCredentialsExportProvider`, and
`rdmo_radar.imports.RadarImport` retain TF behavior. Explicit project/TF subclasses select profiles through
normal RDMO class registration; see the [README](../README.md#mapping-selection).

## Request flows

**XML export:** RDMO dispatches the registered plugin with a project or snapshot. The adapter resolves
`snapshot.project` when necessary, prepares the XML service, and converts its file results into translated
warnings or a ZIP. Missing metadata, mapping issues, and schema violations allow an explicit download.
Generation failures produce a safe error response. Filename sanitization and collision handling belong to
`RadarXmlExportService`; labels, templates, and responses belong to the adapter.

**Credentials export:** the adapter validates the form, prepares a payload through its `get_payload()` hook,
and creates the dataset through `RadarClient`. After RADAR confirms the ID, it constructs the human-facing
URL from that same client's base URL and the request language, then calls `service.store_result`.
Credentials are not stored; the bearer token belongs to the export session.

**OAuth export:** RDMO's `OauthProviderMixin` owns authorization, HTTP requests, and callback replay.
After payload preparation, before creation, the adapter saves project ID, provider class, the dataset,
storage-enabled flag, actual RADAR base URL, and language in a JSON-compatible `export_context`. The callback
uses the registered class's profile and captured scope, never imports a profile named by session data, and
does not construct a metadata service or load project answers. It resolves the saved project only when
storage was enabled. Both services and callbacks use `store_confirmed_result` to handle optional writers
and wrap actual write failures.
Confirmed creation clears the saved operation context; cancellation clears it too.

Both REST providers inherit `get_payload(dataset)` from `RadarExportProviderBase`. By default it returns
`RadarExportService.compute_payload(dataset, responsible_email).payload`. A subclass can return the complete
request dictionary directly or call `super()` and customize it. The provider checks JSON serializability,
then sends the returned dictionary unchanged. Preparation failures produce a form error before submission
or result storage. The hook runs only after valid dataset selection, never for warnings or OAuth replay.
`get_context(dataset)` returns a reader using the same prepared operation and selected scope.

`show_mapping_warnings = None` retains canonical mapping warnings for the default payload hook and suppresses
them when a subclass overrides it. Explicit `True` or `False` enables or disables these profile-derived
warnings. `get_mapping_warnings()` remains separately overridable for custom diagnostics. Raw payloads bypass
canonical metadata validation, and context issues from custom reads are not automatically presented.
The payload hook does not affect XML services or mapping-profile-controlled dataset discovery and storage.

**Import:** RDMO selects `RadarImport` using its file check. The import service parses XML and stages unsaved
Values through the supplied plugin's `get_attribute`, `get_option`, and `values` interfaces. RDMO owns preview
and saves only checked entries during apply. A new dataset index is allocated after the highest persisted
current dataset-title index in the TF profile. Shared contributor/funding fields are merged using prepared
existing Values. Other profiles own destination resolution, allocation, and merge coordinates through their
optional writer-building hook; missing import support raises a clear validation error without TF fallback.

## Value access and operation lifetime

Attributes connect Questions to project Values through their foreign keys. An Attribute can be reused
by multiple Questions and catalogs; Values do not identify one originating Question. Catalog XML uses
full Attribute URIs for these shared references, separately from the Question URIs under `/questions/`.
The domain hierarchy under `/domain/` does not prescribe questionnaire layout or dataset collections.
Catalog placements and complete Value coordinates supply scope information.

Internal dictionaries use `attribute_values_map`, `attribute_placements_map`, and `attribute_lookup_map`
to distinguish prepared Values, catalog scope, and reference resolution. Attribute identity keys are
separate from `Attribute.key` and export dataset selection keys. Existing public arguments and context
fields remain unchanged: `path` may accept a full URI or another supported Attribute reference, while
`values`, `placements`, and `prepared` retain their established construction contracts. Function names,
profile members such as `get_datasets`, and registered entry points also remain compatible.

Factories load project Values once with `filter(snapshot=...).select_related('attribute', 'option')` and group
them by Attribute identity. Persisted models use their primary key; unsaved models use a full URI or object
identity. The internal dictionary keys also retain path/URI labels for operation-local aliases. Catalog
placements and their ancestor anchors use those same keys, canonicalized by identity so cached URI labels
cannot break scope matching for the same primary
key. Fresh Value relations supply the labels when both sources contain that Attribute. Prepared contexts
also accept native Attribute-ID buckets with related Attribute models; unattached native Values are ignored.
Catalog loading and recursive traversal reuse `Catalog.prefetch_elements()`, `pages`, `descendants`, and
`elements`. A small placement conversion retains outermost-first page/questionset
coordinates, repeated placements, non-collection zero coordinates, and empty collection markers.
Path aliases are resolved against the prepared Values and catalog placements, including Attributes with
no Values. Unrelated installed Attributes do not participate. Missing selectors return no Values; ambiguous
selectors return no Values and a deduplicated `MappingIssue`. Exact URI or primary-key selection remains
available even when a path is ambiguous. No installed-model lookup occurs during export mapping.

Component-wise scope matching keeps dataset indices `1` and `10` distinct and supports nested and shared
answers. The established catalog-less fallback remains. There is no separate answer tree or reader hierarchy.
`ProjectReadContext` provides scoped access to prepared project Values and collects lookup diagnostics.
It accepts paths, full URIs, Attribute primary keys, and identifiable Attribute objects in its
read accessors. It also exposes `get_values_by_uri(uri)` and `get_values_by_attribute_id(pk)`. `shared()` and
`group()` retain the prepared dictionaries, selection function, diagnostic field names, and diagnostic list.
The default context reads project Values; a mapping can supply `value_selector(context, attribute_key)`
and `field_names` when it needs specialized scoping or diagnostic names. Legacy path-keyed inputs remain supported:
a bucket containing only path-only synthetic Attributes explicitly represents one fixture Attribute.
Identifiable models in such a bucket are still split by identity; independently keyed URI-less unsaved
models retain object identity. Synthetic inputs never establish equivalence between persisted models.

Option mappings accept full URI keys, which take precedence over legacy `uri_path` keys. Path ambiguity
is checked among the relevant scoped answers, even if the Options would map to the same RADAR value.
`get_option()` returns its default with diagnostics for unresolved/conflicting answers; `map_options()`
returns one mapped result per Value, using `None` for unresolved entries. Specialized Template Framework
readers use the same mechanism and preserve unresolved descriptive labels as `Other` where applicable.

Generic coordinate matching in `metadata/values.py` accepts explicit identity-based constraints and has
no Template Framework paths. `metadata/template_framework.py` owns dataset discovery Attributes,
flat/creator fallbacks, title-only import allocation, the default namespace, and Attribute-to-RADAR
diagnostic field names. The Template Framework profile explicitly supplies its dataset selector and field
names to `ProjectReadContext`; that selector delegates project/group scopes to generic placement matching.
The generic context has no Template Framework dependency.
M7a established these access functions; M7b/M7c select their interpretation through profiles below.

`ProjectWriteContext` merges prepared answers, stages unsaved Values, and collects import diagnostics.
It resolves destinations through RDMO's `get_attribute()` / `get_option()` APIs. Full URIs
resolve exactly. For short paths, `Attribute.build_uri()` and `Option.build_uri()` construct the preferred
URI from the fixed plugin constant `DEFAULT_URI_PREFIX = 'https://rdmorganiser.github.io/terms/'`.
The respective models supply `/domain/` and `/options/`; the plugin does not concatenate those segments.
This constant is independent of Django's `DEFAULT_URI_PREFIX` setting and adds no installation setting
or prefix list. If the official URI is absent, the installed-path fallback must identify one destination,
otherwise it reports ambiguity and stages nothing for that destination. Full URIs never use fallback;
empty paths return no destination. Successful, missing, and ambiguous resolutions are cached per import
context. Existing and staged answers are merged
only for the resolved Attribute, and Option deduplication uses identity. The default import factory shares
one import context between title-index allocation and staging, retaining both caches and diagnostics.
Import resolution may query installed models; staged Values remain unsaved for RDMO preview/apply.

`DATASET_ATTRIBUTES` contains only `project/dataset/id` and `project/dataset/title`, the Attributes used
for Template Framework dataset discovery and scoping. It is not the complete metadata mapping.
`ATTRIBUTE_TO_RADAR_FIELDS` translates Attribute paths into RADAR field names in diagnostics, including
list fields such as `additionalTitles`; it does not enforce scalar values. Renaming these internal
constants does not change discovery, scoping, or warning output.

One service instance represents a prepared operation. Subsequent dataset reads add no Value queries and
select from attribute buckets. Each read gets a fresh diagnostic list; shared/group contexts within that
read share it. Export adapters rebuild their service when the project object, snapshot, or catalog changes.
Profile changes also rebuild the service. Dataset discovery is cached for that service operation and
recomputed when the service changes. Before submission, the selected key must still exist in the current
project's datasets; a stale project or removed record is rejected before remote creation.
For project edits, construct a new service. Preparation is not cached across requests.

## Service and mapping contracts

| Operation | Result |
|---|---|
| `compute_metadata(context, *, dataset, creators, contributors, funding)` | `MappingResult(metadata, issues)` |
| `write_metadata(plugin, metadata, set_index, *, existing_values, context, dataset, creators, contributors, funding)` | Tuple of mapping issues; Values are staged on the plugin. An optional prepared import context must match the plugin and index. |
| `RadarExportService.compute_payload(selection, responsible_email)` | `ExportPayload(payload, issues)`; selection is a dataset or legacy numeric index. |
| `RadarExportService.store_result(selection, radar_id, radar_url)` | `ExportResult(radar_id, radar_url)`; an absent writer succeeds without a local write. |
| `RadarXmlExportService.compute_files(selections)` | XML file results with completeness, schema, and mapping diagnostics. |
| `RadarImportService.process(root)` | Mapping issues returned by the configured writer. |

`RadarMetadata` contains descriptive metadata only. Result issue tuples capture diagnostics for that
operation; they are not mutable state on export instances. REST serialization adds explicit responsible
email and millisecond timestamp to the fixed RDDM 9.3 technical metadata. Missing draft titles get a fallback
without modifying the mapped metadata object. Frozen result dataclasses do not imply deep immutability.

## Mapping profiles and datasets

An `ExportDataset` describes the RDMO source answers for one RADAR dataset. It can represent the whole
Project or one dataset collection entry with complete coordinates. It is a plugin descriptor built from
RDMO's Project, Values, and catalog scope; the metadata and request payload are prepared separately.

`RadarMapping` is a frozen group of ordinary callables, with no registry or subclass requirement:

| Member | Contract |
| --- | --- |
| `get_datasets(project, reader)` | Return export datasets using the prepared reader. Discovery semantics belong to the profile. |
| `build_reader(project, snapshot=None)` | Prepare Values/catalog data once and return a callable accepting the profile's datasets. |
| `compute_metadata(context)` | Return `MappingResult(RadarMetadata, issues)`. Existing component functions remain composable. |
| `build_import_writer(plugin, *, set_index, existing_values, mapping)` | Optional hook returning a metadata-to-staged-Values callable. Owns allocation, destinations, and merging. |
| `store_result(project, dataset, radar_id, radar_url)` | Optional hook writing a confirmed result using the captured scope. Must not require a metadata reader. |

The optional import hook is a writer builder rather than a field-mapping function alone: allocation and
merge preparation must belong to the selected mapping. It receives the optional `mapping=` function override
and can preserve independently replaceable component writers. There is no generic reverse mapping engine.
The registered importer converts unsupported profiles into an explicit validation error.

`ExportDataset(key, label, scope={}, radar_url=None, fallback_file_stem=None)` uses a unique nonempty
string key for Django forms. Its scope contains JSON-compatible dictionaries/lists and scalar values;
the profile owns their interpretation and must treat prepared scope as read-only. Frozen dataclasses do
not freeze nested dictionaries. Dataset scope is copied into the OAuth session before the remote POST.
Keys need not be numeric. An optional filename fallback preserves TF's numeric XML names when titles are
missing; it does not populate descriptive metadata.

`PROJECT_MAPPING` explicitly returns the `project` dataset and maps only `Project.title`. Custom metadata
functions can use the project reference, identity-aware accessors, and snapshot-filtered Values. This
profile has no import writer or local result writer; missing required fields still produce diagnostics.

`TEMPLATE_FRAMEWORK_MAPPING` retains legacy numeric form keys for flat records. Nested keys include the
complete prefix and dataset index, so repeated local indices under different parent collections remain
distinct. Reader constraints include the complete dataset prefix, while shared metadata keeps its existing
project scope. Result destinations capture exact Attribute URIs and scalar coordinates from catalog
placements, including intervening non-collection levels. Ambiguous destinations are never guessed;
confirmed creation then follows the existing local-storage-failure presentation. Fields absent from
prepared catalog/Values retain installed path resolution and the established flat destination fallback.

Adapters use complete `ExportDataset` objects from `get_datasets()` for discovery, labels, existing URLs,
and selection. Each mapping owns its scope representation.
Services still accept legacy numeric indices for direct callers. They do not inspect mapping-owned scope.

Profile selection is a class attribute on a registered XML, credentials, OAuth, or import subclass. The
callback uses that configured class and saved destination; it never rebuilds discovery or metadata after
authorization. Profiles do not configure authentication. Distinct registered classes have distinct native
RDMO session namespaces, allowing project and TF mappings to coexist.
OAuth contexts store the descriptor under `dataset`, together with the provider class and persistence flag.
The callback validates the saved request and destination before replay; the POST checks the destination
again after token exchange. During the POST, an independent copy of the destination is tied to that
request and discarded afterward. A confirmed RADAR ID is always shown if storage cannot be completed;
without a known destination, the confirmation displays the ID without guessing a RADAR URL.
Cancellation clears the pending request, state, operation, and destination while retaining the access token.
RDMO core dispatches callbacks only when a saved state exists, so a late callback after cancellation
receives core's generic integration error without submitting a dataset.

## Extension examples

### Simple project mappings

For an ordinary catalog without dataset collections, the
[complete simple mapping example](../README.md#simple-custom-mapping) needs only a metadata function,
`replace(PROJECT_MAPPING, compute_metadata=read_metadata)`, and a registered `RadarProjectExport` subclass.
The function uses `context.get_text()`, `get_texts()`, and, when needed, `get_option()` or `get_values()`.
It returns `MappingResult(RadarMetadata(...), tuple(context.issues))`. Project discovery and prepared
reading remain defaults; mapping authors do not configure services, datasets, or persistence.
XML and direct export subclasses can select the same mapping without duplicating field interpretation.

Simplicity is an acceptance criterion: a developer familiar withAttributes must be able to map
three fields without learning the internal architecture. The integration test uses a real catalog with
ordinary questions and no dataset collections, loads the example through native registration, and checks both
XML and REST output. The example preserves the original accessor-based programming style; the selected
profile continues to determine mapping behavior. Legacy registrations retain Template Framework defaults.

### Advanced profiles and services

Factories use explicit dependency overrides first, then the selected `profile`. Only an omitted/`None`
profile selects legacy TF defaults. `mapping=` remains the metadata-function override, separate from
`profile=`. Omitting an export `writer` uses the profile hook; explicitly passing `writer=None` disables
persistence. A profile with no writer never falls back to TF storage. Other omitted/`None` dependencies
use their defaults. Factories assemble RDMO integration; services also accept supplied callables directly.

Default construction in an initialized RDMO environment:

```python
from rdmo_radar.factories import build_export_service, build_import_service, build_xml_export_service

export_service = build_export_service(project)
prepared = export_service.compute_payload(0, user.email)
xml_service = build_xml_export_service(project, snapshot=snapshot)
import_service = build_import_service(import_plugin)
```

Explicit project-level construction:

```python
from rdmo_radar.mappings.project import PROJECT_MAPPING

service = build_export_service(project, profile=PROJECT_MAPPING)
dataset = PROJECT_MAPPING.get_datasets(project, service.reader)[0]
prepared = service.compute_payload(dataset, user.email)
# After confirmed remote creation, omitted storage remains a successful no-op.
result = service.store_result(dataset, confirmed_id, confirmed_url)
```

A third-party profile can replace discovery, preparation, and metadata mapping together:

```python
from rdmo_radar.mappings import RadarMapping, ExportDataset
from rdmo_radar.exports import RadarProjectExport
from example_rdmo_plugin.mapping import discover, build_reader, compute_metadata, store_result

EXAMPLE_MAPPING = RadarMapping(
    get_datasets=discover,  # e.g. ExportDataset('record-a', 'Record A', {'coordinate': [1, 3]})
    build_reader=build_reader,
    compute_metadata=compute_metadata,
    store_result=store_result,
)


class ExampleRadarExport(RadarProjectExport):
    mapping = EXAMPLE_MAPPING
```

Register `example_rdmo_plugin.exports.ExampleRadarExport` using RDMO's existing dotted class mechanism. For direct
export, subclass the corresponding provider and select the same profile. OAuth callbacks call its
`store_result` hook with the saved dataset, rather than a service writer created in an earlier request.

Replace one mapping while keeping the others:

```python
from functools import partial

from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.types import PersonOrOrganization


def read_creators(context):
    return [PersonOrOrganization('Example University')]


mapping = partial(compute_metadata, creators=read_creators)
export_service = build_export_service(project, mapping=mapping)
xml_service = build_xml_export_service(project, mapping=mapping)
```

Import mappings use the same callable pattern, for example
`build_import_service(import_plugin, mapping=partial(write_metadata, funding=example_funding_writer))`.
The writer receives the mapping context and funding references and stages Values through that context.
When a profile has no import builder, an explicit import `mapping=` owns its allocation and receives the
supplied `set_index` unchanged, including `None`. An explicit import `writer=` bypasses profile preparation.

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
imported explicitly from `rdmo_radar.metadata.read_context` and `rdmo_radar.metadata.write_context`:

```python
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.write_context import ProjectWriteContext
```

## Persistence and failures

`store_export_result(project, set_index, radar_id, radar_url)` stores the supplied complete URL unchanged.
By default it updates only the selected dataset's current flat Values (`snapshot=None`, `set_prefix=''`,
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
M7a passed 276 tests with one expected upstream failure on each RDMO 2 target, using Python 3.14.7,
Django 5.2.18, DRF 3.18.3, and pytest 8.4.2. Its 26 added regression cases cover identity/URI access, local
path ambiguity, catalog-only collisions, unsaved and deferred models, Option collisions, namespace-safe
import merging/allocation, and cached resolution failures. Metadata/diagnostic hashes and query counts
matched a clean `9bfe6f1` baseline at 2, 50, and 100 datasets: 16 setup queries on RDMO 2.5.2, 24 on 2.5.1,
and zero subsequent queries on both.

M7b/M7c pass 323 tests with the same expected upstream failure on each RDMO 2 target. The additional 47
cases cover explicit project/TF modes, custom profiles through native registration, complete nested scopes,
writer precedence, unavailable imports, staging/allocation ownership, identity matching across cached URI
labels, stale selections, and real XML/credentials/OAuth flows. Callback tests change later form state and
disable all reader/discovery functions, while checking custom writers, disabled storage, confirmed-result
failures, and captured dataset scope. The RDMO 2.5.2 benchmark retains its metadata/diagnostic hashes, 16 setup
queries, and zero queries after preparation for 2, 50, and 100 datasets.

The existing RDMO 3 backend environment uses revision `a14a08b74e91e75da9c79f0606ce6fdb5c86b64e`.
That source lacks the legacy project-export views and form template. Running
`python -m pytest --ignore=tests/test_host.py -m 'not legacy_presentation'` passes 295 tests, with one
deselected legacy presentation case and one expected upstream failure. These checks do not establish
RDMO 3 frontend support. Arbitrary catalog import implementations and RDMO core improvements remain
separate follow-ups; the profile interface provides the import boundary without guessing catalog semantics.

Demonstrated upstream improvements:

- Boundary-safe `ValueQuerySet.filter_set`: prefix matching selects dataset `10` when requesting `1`.
  The minimized reproduction is retained in `tests/test_value_scopes.py`.
- A public catalog placement/scope helper covering repeated placements and empty page/questionset markers.
  The plugin currently performs only the conversion and scope matching described above.
  RDMO 3's `compute_value_maps()` in `projects/utils.py` already groups Values by Attribute IDs and set
  coordinates, but does not provide the catalog placements or empty collection markers needed here.
  Its AnswerTree adds rendering/condition behavior; M7a retains native core prefetch/traversal and small
  dictionary preparation rather than introducing another tree. Identity-aware placement preparation and
  coordinate constraints could be replaced by a future public core helper.
- OAuth transport timeout/request hooks and safer core logging. The inspected core mixin does not expose
  these hooks and logs some upstream bodies itself; plugin-owned client error handlers log only status.

These are separate upstream tasks. See [metadata mapping](metadata-mapping.md) and
[the RADAR REST contract](radar-api-contract.md) for field semantics and API evidence.
