# Legacy mapping showcase

`rdmo_radar.mappings.legacy` ports the original plugin's active `get_dataset()` and
`get_name()` mappings into the current architecture. It is an export-only comparison
profile, independent of the Template Framework configuration. Its source selection follows
the old **REST provider** where the old XML and REST implementations disagreed; supported Options come from the current shared RADAR vocabularies.

The profile contains three ordinary pieces:

- `fields.py`: `LEGACY_FIELDS` and its canonical field readers.
- `vocabulary.py`: complete copies of the shared RADAR crosswalks and two historical name-identifier
  scheme overrides.
- `__init__.py`: prepared answer access, dataset discovery, result storage, and `LEGACY_MAPPING`.

No legacy exporter, renderer, or authentication implementation runs alongside the current
pipeline. Both formats consume the same `RadarMetadata`; the shared services provide
serialization, diagnostics, previews, and the export lifecycle.

RADAR vocabulary data is defined once in `rdmo_radar.mappings.common.vocabulary`. Common tables
are read-only; legacy and TF expose independent dictionary copies through existing public names. Legacy
uses the complete compatible tables, including all twelve language Options, newer contributor roles,
resource types, ODC licenses, survey data sources, and additional relations. Historical aliases such as
`contact_persion` and capitalized `Compiles` remain supported.

The only name-identifier scheme overrides are `name_identifier_scheme/insi` → `ISNI` and
`name_identifier_scheme/grid` → `GRID`. Common/TF definitions map these entries to `Other`.
The existing `RESOURCE_TYPE_OPTIONS` name refers to the shared general resource-type vocabulary.

Related identifiers use the dedicated 24-type RADAR vocabulary rather than the general identifier table.
Supported additions include arXiv, RAiD, and SWHID. `Other` and `RADAR` are unmapped for related identifiers:
the existing mapping warning is recorded, the identifier text is retained, and the type stays unset.
XML validation reports the missing required type for completion. Alternate identifiers continue to accept
the general type vocabulary, including `RADAR`.

All three built-in profiles use `common.readers.prepare_project_read()` to load Values, catalog
placements, and identity lookups once per operation. Each profile still constructs its own contexts.
Legacy retains exact-coordinate access, first/last-answer selection, independent diagnostics, and its
existing discovery and storage rules. See [shared profile definitions](architecture.md#shared-profile-definitions)
for the boundary between common definitions and profile policies. No registration changes or migrations
are required.

## Register alongside the other mappings

Use separate keys to compare the legacy and Template Framework interpretations of a project:

```python
from django.utils.translation import gettext_lazy as _

PROJECT_EXPORTS += [
    ('radar-legacy-xml', _('as RADAR XML (legacy)'), 'rdmo_radar.exports.RadarLegacyExport'),
    ('radar-tf-xml', _('as RADAR XML (Template Framework)'), 'rdmo_radar.exports.RadarTemplateFrameworkExport'),
    ('radar-legacy-oauth', _('to RADAR (legacy, OAuth)'), 'rdmo_radar.exports.RadarLegacyExportProvider'),
    (
        'radar-legacy-credentials', _('to RADAR (legacy, credentials)'),
        'rdmo_radar.exports.RadarLegacyCredentialsExportProvider',
    ),
]
```

Configure authentication through `RADAR_PROVIDER` as usual. The three named classes only
select `LEGACY_MAPPING`; they contain no separate workflow logic. No legacy importer is
provided. Passing this profile to the import factory reports that import is unavailable.

For local comparison, enable `RADAR_DEBUG` and the independent preview settings described
in the [README](../README.md). The mapping and source-answer panels explain the historical
selection rules without submitting datasets.

## Compare the mapping definitions

The old exporter put both selection and mapping into an export subclass:

```python
dataset['language'] = self.get_option(
    self.language_options,
    'project/dataset/language',
    set_index=set_index,
)
```

The new profile declares that field independently of the adapter and serializer:

```python
from functools import partial

from rdmo_radar.metadata.fields import FieldMapping, Source
from rdmo_radar.mappings.legacy.fields import first_option
from rdmo_radar.mappings.legacy.vocabulary import LANGUAGE_OPTIONS

language_fields = FieldMapping(readers={
    'language': partial(
        first_option,
        source=Source('project/dataset/language'),
        option_map=LANGUAGE_OPTIONS,
    ),
})
```

`first_option` is a legacy-specific strategy. It preserves the original first-answer
behavior, even when a later answer would be usable. The generic field readers retain
their existing conflict detection and normalization. Historical policies are contained
in this profile rather than added to the generic RDMO access layer.

To replace one field, copy this into `example_rdmo_plugin/exports.py`:

```python
from dataclasses import replace
from functools import partial

from rdmo_radar.exports import RadarLegacyExport
from rdmo_radar.mappings.legacy import LEGACY_FIELDS, LEGACY_MAPPING
from rdmo_radar.mappings.legacy.fields import first_text
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.fields import Source

EXAMPLE_FIELDS = replace(LEGACY_FIELDS, readers={
    **LEGACY_FIELDS.readers,
    'title': partial(first_text, source=Source('https://example.org/terms/domain/research/title')),
})


class ExampleRadarExport(RadarLegacyExport):
    mapping = replace(
        LEGACY_MAPPING,
        compute_metadata=partial(compute_metadata, fields=EXAMPLE_FIELDS),
    )
```

Discovery and storage remain unchanged in this example. A missing custom title does not
silently enable the old title reader. Ordinary new mappings can instead select the
[generic field strategies](architecture.md) when legacy selection is unnecessary.

## Historical field sources

| Canonical field | Historical source and selection |
| --- | --- |
| Title | First `project/dataset/title`, then first `/id`, then `Dataset #N`. |
| Creators/contributors | `/creator/name` or `/contributor/name` markers under the dataset index prefix; their structured fields, identifier, type, and first nonempty affiliation. Name type defaults to `Personal`, identifier scheme to `ORCID`, contributor role to `Other`. |
| Publishers | First `/publisher`, then first `/preservation/repository`. |
| Production/publication year | RDMO typed date year from `/created` or `/issued`, falling back to `/data_publication_date`. |
| Subject areas | `/subject` Values if present, otherwise root `project/research_field/title`; false answers are skipped, unknown subjects retain their native Value label as `Other`. Duplicate subjects remain duplicated. |
| Resource | `/resource_type` text with the Option at `/resource_type_general`. |
| Alternate/related identifiers | Dataset-prefixed `/alternate_identifier/identifier` and `/related_identifier/identifier` groups with their explicit type/relation Options. |
| Rights | Last `/sharing/conditions` Value, including its native label for `Other`. |
| Rights holders | Nonempty `/sharing/rights_holder` text Values, preserving order and duplicates. |
| Description | First `/description`, categorized as `Abstract`. |
| Keywords | Root `project/research_question/keywords`, retaining nonempty text in order, including whitespace and duplicates. |
| Language | First `/language` answer; all twelve shared European-language Options, with no text-language inference. |
| Data sources | First `/data_source` text with the first `/data_source_detail` Option. |
| Funding | Root `project/funder/id` groups; `/name`, `/name_identifier`, `/name_identifier_scheme`, and `/programme/url`, `/number`, `/title`. |

Except where a full path is shown, `/...` in this table is relative to `project/dataset`.
The primary identifier and data processing were commented out in the original mapping
and stay unset. Newer owner, publisher-responsibility, GND keyword, creation-method, PID,
and rights-holder Attributes do not become implicit fallbacks.

## Selection, identity, and persistence

Only empty-prefix `project/dataset/id` markers discover datasets. Title-only projects and
nested markers produce no legacy datasets. Repeated marker indices are rejected because
they cannot identify unique form selections.

Dataset fields use exactly `set_prefix=''` and the selected `set_index`. People and
identifier groups use exactly `set_prefix=str(dataset_index)`; funding groups use the
empty prefix, and shared keywords/subjects use the empty prefix at index zero. Catalog
placements do not broaden these historical coordinates. Indices `1` and `10` remain
separate. The selected project/snapshot Values are loaded once, then reused for all fields.

Scalar getters use the first answer by collection order, including a blank first answer.
A blank first scalar can therefore activate its next Attribute fallback even if a later
answer at the first Attribute contains text. Lists retain all nonempty text; rights use
the last answer. Provider `external_id` values are not promoted into names or identifiers.

These selection rules still use identity-aware lookup. Ambiguous Attribute paths produce
diagnostics and no combined Values; explicit URIs or IDs can select one Attribute. Option
path collisions remain diagnostic and cannot arbitrarily select another namespace.

Confirmed IDs and URLs are written at the selected dataset index, empty prefix, and
collection index zero, to `project/dataset/radar_id` and `/radar_url`. Captured destinations
use full Attribute URIs when available. Missing destination Attributes are skipped;
ambiguous destinations or database failures use the existing storage-error confirmation.
Writes are atomic, affect live Values, and leave snapshots and other indices untouched.
OAuth callbacks use captured destinations without reconstructing the metadata reader.

## Deliberate differences from the original plugin

| Original behavior | Packaged legacy profile |
| --- | --- |
| XML and REST data-source vocabularies disagreed. | REST rules define both formats: trial → `Trial`, organism → `Organism`, tissue → `Tissue`. |
| XML referenced an undefined `resource_type_options` member. | The historical resource-type vocabulary is configured explicitly. |
| Related identifiers used the general identifier-type vocabulary. | Use the dedicated RADAR list; unsupported types warn and retain the identifier text without a type. |
| Vocabulary lists had fewer supported Options. | Adopt the complete shared compatible lists while retaining historical aliases. |
| The `insi` Option produced invalid `INSI`. | The key stays `name_identifier_scheme/insi`, with canonical value `ISNI`. Other historical keys, including `contact_persion`, remain usable. |
| Structured given/family names caused the main name field to disappear. | Preserve the required original name answer alongside the structured parts. |
| XML used uppercase language codes and one subject label had leading whitespace. | Use schema-valid canonical language codes and the REST subject spelling; serializers own wire spelling. |
| REST used schema 9.1 and second-based timestamps. | Use the current shared RDDM 9.3 request, millisecond clock, and serializer wire shapes. |
| XML filenames used identifiers/collection labels. | Use the current sanitized, unique title-based filenames. |
| Native path queries could combine namespaces; writes were independent. | Keep current identity diagnostics, atomic persistence, and OAuth safeguards. |

This profile reproduces historical answer selection, not byte-for-byte obsolete requests.
It can intentionally produce incomplete drafts: the current completeness and XML validation
diagnostics remain visible. For a current Template Framework catalog, use its explicit profile.
