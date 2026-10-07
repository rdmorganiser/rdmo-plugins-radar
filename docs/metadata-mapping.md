# RADAR 9.3 metadata mapping

The export mapping implements the conservative first version agreed from the 2026 Template Framework workbook:

- [Field mapping CSV](<Mapping_radar-plugin_dmp-tf.xlsx/Mapping_radar-plugin_dmp-tf.xlsx - [neu]Mapping RADAR-RDMO.csv>)
- [Subject mapping](<Mapping_radar-plugin_dmp-tf.xlsx/[neu]Mapping Fachgebiet.html>)
- [DMP4NFDI 2.0.0 catalog](../tests/xml/dmp4nfdi_v2-0-0.xml)
- [Prototype project](<../tests/xml/RADAR Plugin Testprojekt.xml>)

The internal `RadarMetadata` model uses RDDM XML spellings, such as `Survey` and `IsCitedBy`.
Both XML downloads and direct exports use the same readers. REST enum spelling is converted only
by the API adapter. The reviewed crosswalks are Python code in `metadata/crosswalks.py`; exports do
not parse spreadsheets or fetch vocabularies over the network.

## Answer scope and dataset discovery

RDMO collects dataset labels through collection pages, without requiring a separate question.
Both export paths discover datasets through `project/dataset/id` and `project/dataset/title`.
An explicit title takes precedence over the collection label. The collection label is never used
as a persistent identifier. If neither contains text, direct drafts receive `Dataset #N`; XML
reports the missing title. ZIP filenames use the resolved label and are sanitized and made unique.

The answer index reads only the selected project/snapshot and follows the catalog's page and
questionset nesting, including non-collection questionsets. For example, dataset 0's description
can have prefix `0`, while its license has an empty prefix and set index 0. Project-level funding,
keywords, and subjects are shared across datasets. Prefixes are matched as complete components,
so dataset 1 never receives dataset 10's answers. Attributes absent from the catalog retain their
established flat layout (and the established nested creator layout).

Collection indices may be sparse. Multiple distinct scalar answers produce a mapping warning
instead of choosing an arbitrary value. Controlled mappings use option URI paths, not translated
labels. Text preserved alongside `Other` uses the option's current RDMO language and any supplied
free text. Supported person identifiers prefer `external_id` over provider display text.

## Implemented exports

| RADAR field | Source and behavior |
| --- | --- |
| Title | `project/dataset/title`, then the `project/dataset/id` collection label. |
| Identifier | Existing `project/dataset/data_publication_pid` support; scheme from recognized `project/dataset/pids/system` options. No identifier is invented. |
| Subject areas | `project/research_field/title`; all 48 catalog DFG options mapped using the subject sheet. Every explicitly listed category is emitted, with duplicate entries removed. `Other` retains the original label. The uncertain Materials Engineering entry stays `Other`; workbook “Veterinary” uses the schema spelling `Veterinary Medicine`. The stray Jurisprudence note on the Economics row does not override its explicit Economics mapping. |
| Resource | `project/dataset/description`. Existing RADAR resource-type options on `project/dataset/format` remain supported; the catalog's file-format options do not imply a RADAR resource type. |
| Data sources | `project/dataset/creation_methods`: observations → `Observation`; polls/surveys → `Survey`; laboratory/social/field experiments → `Trial`; remaining choices → `Other`. Preserve labels and free text. Unknown choices produce a warning and retain their text as `Other`. |
| Rights | `project/dataset/sharing/conditions`: CC-BY, CC-BY-NC, CC-BY-ND, CC-BY-SA, CC0, ODC-By, ODbL, and Other. Preserve additional text. Multiple distinct selections omit rights and report all selections for completion in RADAR. |
| Funding | Discover populated name, grant-number, and programme fields without requiring a funder-ID marker. Keep fields grouped by their answer coordinates. `project/funder/id` remains a set marker, never a persistent funder identifier. Existing programme-URL support remains available. |
| Keywords | All `project/research_question/keywords` text values, ordered and deduplicated. |
| Software | The explicit `dmp4nfdi/v2-0-0/ur00` usage-requirement choice with free text → software name and `Resource Viewing`. No parsing of names/versions or mapping of other usage requirements. Missing version is reported. |
| Creators and contributors | Preserve established creator and partner fields, including structured names and external ORCID values. Partner responsibility options are not names. Contributor roles remain `Other`; broader role/person mappings are deferred. |
| Other established fields | Preserve acronym as additional title, recognized language options, rights-holder names, geolocation region, and `project/dataset/method` processing text when available. |

## Incompleteness and deferred decisions

The supplied catalog has no explicit dataset-title, creator-name, language, geolocation,
rights-holder-name, dataset-method, or funder-ID attribute. Missing answers cannot be manufactured
by the exporter. The prototype intentionally remains incomplete for publication.

New mappings for production/publication dates, descriptive description types, contributor roles,
related/alternate identifiers, persistent funder identifiers, and processing interpretations are
deferred. Project dates do not become dataset production dates. `dataset/usage_description` is not
treated as a processing statement. Fields marked “n/a (2026)” do not trigger new mappings; compatible
existing readers are retained. No catalog changes or answer migrations are required.

Mapping issues carry a target, source attribute, and reason, but are never serialized into RADAR
metadata. XML shows mapping issues, missing required fields, and bundled-XSD validation errors
before allowing “Download anyway”. Only XML generation failures block download. The existing direct
export form shows incomplete fields and mapping issues; datasets can still be created as drafts.
Completing missing metadata in RADAR remains necessary before archival or publication.

## Import compatibility and verification

RADAR XML import retains its existing mappings, merge behavior, and warnings for unsupported
fields. Export-only crosswalks are not reversed: a RADAR category can correspond to multiple DFG
subjects. Additional ODC license options are shared with the existing license vocabulary.

Tests import the supplied catalog into an isolated database and load the prototype's values with
their original coordinates and options. They exercise both providers, XML validation/download,
subject and source vocabularies, licenses, nested datasets, funding groups, and snapshot isolation.
The expected prototype output contains two labeled datasets, the first dataset's description,
three source entries (`Survey`, `Trial`, `Trial`), its CC-BY license, and shared keywords, funding,
and the Ancient Cultures subject retained as `Other` with its label.
