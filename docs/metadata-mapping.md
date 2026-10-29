# RADAR 9.3 metadata mapping

The registered class selects a mapping profile. Explicit Template Framework classes
use the mapping described below; generic adapters require a configured profile. Explicit project classes export one record with `Project.title` and
leave other fields unset unless an installation supplies custom functions. They neither infer metadata
from `Project.description` nor write results to Template Framework Attributes. Missing publication fields
remain visible. See [mapping selection](../README.md#mapping-selection) and the
[profile contract](architecture.md#mapping-profiles-and-datasets).

The export mapping includes the reviewed 27 October 2026 update to the Template Framework workbook.
The source is `Mapping_radar-plugin_dmp-tf.xlsx - [neu]Mapping RADAR-RDMO-271026.csv`, reviewed on
2026-10-28. The original subject crosswalk and regression inputs remain:

- Workbook subject sheet `[neu]Mapping Fachgebiet`, implemented in `mappings/template_framework/crosswalks.py`.
- [DMP4NFDI 2.0.0 catalog](../tests/xml/dmp4nfdi_v2-0-0.xml)
- [Prototype project](<../tests/xml/RADAR Plugin Testprojekt.xml>)

The internal `RadarMetadata` model uses RDDM XML spellings, such as `Survey` and `IsCitedBy`.
Both XML downloads and direct exports use the same readers. REST enum spelling is converted only
by the API adapter. The reviewed crosswalks are Python code in `mappings/template_framework/crosswalks.py`; exports do
not parse spreadsheets or fetch vocabularies over the network.

## Answer scope and dataset discovery

RDMO collects dataset labels through collection pages, without requiring a separate question.
Both export paths discover datasets through `project/dataset/id` and `project/dataset/title`.
An explicit title takes precedence over the collection label. The collection label is never used
as a persistent identifier. If neither contains text, direct drafts receive `Dataset #N`; XML
reports the missing title. ZIP filenames use the resolved label and are sanitized and made unique.

Prepared Value access reads only the selected project/snapshot and follows the catalog's page and
questionset nesting, including non-collection questionsets. For example, dataset 0's description
can have prefix `0`, while its license has an empty prefix and set index 0. Project-level funding,
keywords, and subjects are shared across datasets. Prefixes are matched as complete components,
so dataset 1 never receives dataset 10's answers. Attributes absent from the catalog retain their
established flat layout (and the established nested creator layout).

Collection indices may be sparse. Multiple distinct scalar answers produce a mapping warning
instead of choosing an arbitrary value. Attribute paths must be unambiguous within prepared Values and
catalog placements; otherwise access reports a mapping issue and requires an exact URI or Attribute ID.
The Template Framework mapping retains path-based access and catalog-less flat dataset markers. No
dataset is invented when marker Values are absent.

Controlled mappings accept full Option URIs, with existing URI-path crosswalks retained for unambiguous
scoped answers. Options from distinct namespaces sharing a path are not silently conflated, even when
their mapped RADAR values agree. Translated labels do not identify vocabulary entries.
Text preserved alongside `Other` uses the option's current RDMO language and any supplied
free text. Supported person identifiers prefer `external_id` over provider display text.

Export datasets retain complete dataset coordinates, including parent collections. Two nested datasets
with index 3 under different parent entries have different selection keys and readers. The profile supplies
labels and existing RADAR URLs; adapters do not read Template Framework paths themselves. Result writes
use captured scalar coordinates and Attribute URIs when available. Ambiguous or non-scalar destinations
produce the existing storage-failure result page after confirmed creation rather than an arbitrary write.

## Implemented exports

| RADAR field | Source and behavior |
| --- | --- |
| Title | `project/dataset/title`, then the `project/dataset/id` collection label. |
| Identifier | Existing `project/dataset/data_publication_pid` support; scheme from recognized `project/dataset/pids/system` options. Only `DOI`, `Handle`, and `RADAR` are accepted as primary types. A populated PID with a missing, conflicting, or unsupported scheme is omitted with diagnostics. No identifier is invented. |
| Subject areas | `project/research_field/title`; all 48 catalog DFG options mapped using the subject sheet. Every explicitly listed category is emitted, with duplicate entries removed. `Other` retains the original label. The uncertain Materials Engineering entry stays `Other`; workbook “Veterinary” uses the schema spelling `Veterinary Medicine`. The stray Jurisprudence note on the Economics row does not override its explicit Economics mapping. |
| Resource | `project/dataset/description`. Resource type stays unset because there is no confirmed source. `project/dataset/format` describes file/media formats and is never read as a RADAR resource type. Complete the resource type in RADAR. |
| Data sources | `project/dataset/creation_methods`: observations → `Observation`; polls/surveys → `Survey`; laboratory/social/field experiments → `Trial`; remaining choices → `Other`. Preserve labels and free text. Unknown choices produce a warning and retain their text as `Other`. |
| Rights | `project/dataset/sharing/conditions`: CC-BY, CC-BY-NC, CC-BY-ND, CC-BY-SA, CC0, ODC-By, ODbL, and Other. Preserve additional text. Multiple distinct selections omit rights and report all selections for completion in RADAR. |
| Rights holders | Use only `project/dataset/ipr/rightsholder` for export and import. Preserve ORCID/ROR provider identities alongside names during export; import writes names and warns about unsupported identity data. |
| Publishers | `project/dataset/curation/responsible_person/name`: text or provider names, with ORCID/ROR identity when available. Responsibility Options are not publisher names. A custom publisher callable can replace this reader. |
| Funding | Read name, grant-number, and programme fields grouped by answer coordinates. Split `project/funder/name` provider answers into funder name and identifier. Optional `project/funder/id/type` supplies an explicit identifier scheme; it never creates an identifier. `project/funder/id` remains a set marker. Existing programme-URL support remains available. |
| Keywords | Combine `project/research_question/keywords` and `/keywords/gnd`. Free text stays untyped; GND entries retain label, scheme, scheme URI, term URI and classification code. Deduplicate free text by trimmed text and GND terms by identity, preserving distinct terms with the same label. |
| Software | The explicit `dmp4nfdi/v2-0-0/ur00` usage-requirement choice with free text → software name and `Resource Viewing`. Optional confirmed name/version Attributes can be configured in the TF field mapping. No parsing of versions from names. Missing version is reported. |
| Creators | Prefer `project/dataset/owner/name`, `/given_name`, `/family_name`; fall back to established `project/dataset/creator/*`. Read provider identities and creator-linked affiliations. Project coordination organisations require a custom mapping. |
| Contributors | Prefer `project/contributor/*`, retaining `project/partner/*` as fallback. Read actual names, structured names, person/entity Options, ORCID, organisation and ROR affiliation fields, including SMP autocomplete answers. Accept explicit recognized RADAR roles; unknown/conflicting roles become `Other` with a warning. Responsibility labels never become names. |
| Language | `project/dataset/language`: recognized controlled Options, or supported language names/codes entered as text. Normalize to schema-valid ISO 639-3 codes; see the selection below. |
| Other established fields | Preserve acronym as additional title, geolocation region, and `project/dataset/method` processing text when available. |

## Software sources

`mappings/template_framework/fields.py` reserves `SOFTWARE_NAME_PATH` and
`SOFTWARE_VERSION_PATH`, both initially `None` because no suitable TF Attributes have
been confirmed. Once available, set these to the correct Attribute paths. Setting only
the version path attaches explicit versions to the existing usage-requirement names;
setting a name path selects dedicated free-text names instead of usage requirements.
The software category remains `Resource Viewing` and can be changed in the field configuration.

The reusable reader accepts `source=Source(name_attribute)`, an optional
`version_source=version_attribute`, and an optional `option_map`. Without an Option map,
only plain-text names are accepted; with a map, only enabled requirement answers supply
names. Versions are read from the software entry's complete answer coordinates and related
catalog descendants. Use separate collection groups for separate software entries.
Multiple names in one group make the version association ambiguous; the reader preserves
the names, omits their versions, and reports the ambiguity. Missing or conflicting versions
also preserve names with completion warnings. A version-only answer never creates software.
Both XML and REST receive explicit mapped versions. Drafts without a version retain the
existing XSD warning because `softwareVersion` is required whenever software is emitted.

## Dataset language

`TF_FIELDS` explicitly binds `read_language` to `Source('project/dataset/language')` and the TF
Option crosswalk. The reusable signature is `read_language(context, *, source, option_map, target,
normalizer=normalize_language)`; it selects no Attribute or RDMO Options by default.
Replace its field callback to use a different source or normalizer; see the
[mapping override example](../README.md#typed-metadata-and-template-framework-overrides).
Missing or unsupported values at an overridden source do not enable fallback to the TF Attribute.
Import has its own writer and independently configured destinations/crosswalks.

The dataset language reader accepts this initial European selection from text answers, as well as
controlled Options with the listed `language/<ISO 639-1>` paths. Existing English/German Options retain
their behavior. Option identity is authoritative; arbitrary Option labels are not used as vocabulary keys.
Additional language names and aliases can be reviewed in the small static table in `metadata/languages.py`.

| German name | English name | ISO 639-1 input / Option suffix | Canonical XML code |
| --- | --- | --- | --- |
| Englisch | English | en | eng |
| Deutsch | German | de | deu |
| Französisch | French | fr | fra |
| Dänisch | Danish | da | dan |
| Niederländisch | Dutch | nl | nld |
| Schwedisch | Swedish | sv | swe |
| Finnisch | Finnish | fi | fin |
| Italienisch | Italian | it | ita |
| Spanisch | Spanish | es | spa |
| Portugiesisch | Portuguese | pt | por |
| Polnisch | Polish | pl | pol |
| Tschechisch | Czech | cs | ces |

Names and codes are matched after Unicode normalization, trimming and case folding. Common native names
and German ASCII spellings such as `Daenisch` and `Franzoesisch` are supported too. Canonical three-letter
codes are valid inputs. Bibliographic aliases `ger`, `fre`, `dut` and `cze` normalize to `deu`, `fra`, `nld`
and `ces`: the bundled RADAR XSD accepts the latter spellings, despite the `ger`/`fre` examples in the PDF.
The [Library of Congress code guidelines](https://www.loc.gov/aba/pcc/scs/documents/ISO-639-3-guidelines.pdf)
also distinguish those ISO 639-2/B aliases from ISO 639-3. REST receives the corresponding uppercase enum,
for example `Deutsch` → canonical/XML `deu` → REST `DEU`. RADAR owns the displayed language name.

Equivalent answers such as `Deutsch`, `de`, `ger` and a German Option agree on one language. Unsupported
answers, lists in one text field, or multiple different languages omit the scalar field with a mapping
warning. Blank or absent answers are omitted without a warning; the export language is not inferred from
the RDMO interface locale. Selection remains dataset/snapshot scoped and performs no remote lookup.
Import keeps its Option-based behavior, including the added `language/<ISO 639-1>` entries when installed;
no catalog Options or answer migrations are created automatically.

## Incompleteness and deferred decisions

The supplied catalog has no explicit dataset-title, creator-name, language, geolocation,
rights-holder-name, dataset-method, or funder-ID attribute. Missing answers cannot be manufactured
by the exporter. The prototype intentionally remains incomplete for publication.

New mappings for production/publication dates, descriptive description types,
related/alternate identifiers, inferred contributor roles and processing interpretations are
deferred. Project dates do not become dataset production dates. `dataset/usage_description` is not
treated as a processing statement. TS4NFDI and ontology metadata are deferred pending clarification of
RADAR's requirements. Unsupported terminology identifiers retain their labels with a warning; they are
not exported as GND. No catalog changes or answer migrations are required.

## 27 October 2026 Attribute audit

The CSV still marks several rows `n/a (2026)` and contains tentative comments. The approved update
supports the following optional source paths when installations supply them; it does not create domain
Attributes or parse the CSV at runtime. The domain-status column describes the checked-in reference
catalog snapshot, not every RDMO installation.

| CSV field | Source and status | Implementation decision |
| --- | --- | --- |
| Creator name / structured names | `project/dataset/owner/name`, `/given_name`, `/family_name`: absent | Prefer this source family when populated; retain legacy creator fields as fallback. |
| Creator institution | `project/coordination/organization`: present | Custom mapping only. It neither supplies automatic creators nor establishes their affiliations. |
| Creator identifier | CSV leaves `/orcid` and `/ror` children unspecified | Optional `project/dataset/owner/orcid` and `/ror` are plugin conventions. Provider identities in name answers are supported too. |
| Creator affiliation | `project/dataset/owner/organization/name` and `/identifier/value`, `/identifier/type`: absent | Read creator-linked names and explicit scheme/value pairs, including nested collections and intervening non-collection levels. |
| Publisher | `project/dataset/curation/responsible_person/name`: present | Text/provider names only. Existing Horizon Europe responsibility choices do not name entities; they produce a mapping issue. |
| Rights holder | `project/dataset/ipr/rightsholder`: absent | Sole export source and import destination. Do not substitute `project/dataset/ipr/owner/name`, which is used for a yes/no question. |
| GND keyword | `project/research_question/keywords/gnd`: present | Read alongside the established free-text Attribute. The Attribute supplies GND context for bare external IDs. Creatable free text stays free text. |
| Contributor | `project/contributor/person_or_entity`: present | This is a discriminator, not a name. Read sibling `name`, `given_name`, `family_name`, `orcid`, `organization`, `organization/ror` and SMP autocomplete fields. |
| Contributor role | CSV: `dmp/contributor/role`, absent; actual domain: `project/contributor/role`, present | Prefer actual domain semantics. Also accept the literal CSV alias when it shares the contributor's prepared catalog group. Match Option identities or exact canonical RADAR role text, never translated labels or task descriptions. |
| Description type | `project/dataset/description/type`: absent | Deferred, following the explicit CSV instruction not to choose a mapping. |
| Funder identifier/type | `project/funder/name`: present; `/id/type`: absent | Split label and external ID from the same answer; accept an explicit supported scheme. A marker, scheme alone or plain name never becomes an identifier. |
| Other source paths | Title, research field, resource description, licence, language, geolocation, creation methods, method, grant/programme fields | Retain established readers and crosswalks. Language remains optional when supplied by an installation. |
| Ambiguous interpretations | Format as resource type, datatype as source detail, re-used dataset URI without identifier/relation types | Deferred. Preserve the current incomplete-draft diagnostics instead of inventing required classifications. |

The reviewer's correction confirms that `project/dataset/sharing/rights_holder` in the original-plugin
column was an incorrect reference, not a supported legacy Attribute. It is neither read nor written.
If the correct IPR Attribute is not installed, export leaves rights holders unset and import reports
the missing destination without creating an Attribute or migrating existing answers.

Owner and contributor source families take precedence over legacy families when name-bearing answers
are present. Both populated families produce a warning; fields are not joined across them. Ambiguous preferred Attribute
identities do not silently enable fallback. Names and identifiers remain associated through full answer
coordinates and catalog ancestry; matching numeric indices alone do not establish a relationship.

Known provider display decorations are removed before export. In particular, ROR's display URL is not
part of the organisation name, and GND identifier links or synonym decorations are not keyword labels.
`external_id` has precedence; its scheme must be established by an explicit field or recognized URI/link
format. Conflicting identifiers are omitted with diagnostics. A provider configured to store only an ID
cannot supply the mandatory entity name; the exporter reports this without looking it up remotely.

REST and XML use the same canonical identities and standard scheme URIs. `Other` becomes `OTHER` only
for REST controlled enums. Free-text affiliation schemes and URIs retain their spelling. RADAR accepts
one affiliation per creator/contributor; additional mapped affiliations remain in canonical metadata,
produce a warning, and are omitted from both outputs after the first.

Mapping issues carry a target, source attribute, and reason, but are never serialized into RADAR
metadata. XML shows mapping issues, missing required fields, and bundled-XSD validation errors
before allowing “Download anyway”. Only XML generation failures block download. The existing direct
export form shows incomplete fields and mapping issues; datasets can still be created as drafts.
Completing missing metadata in RADAR remains necessary before archival or publication.

## Import compatibility and verification

RADAR XML import retains its merge behavior and warnings for unsupported fields. Resource types
are not imported into `project/dataset/format`; they produce an unsupported-mapping warning.
Export-only crosswalks are not reversed: a RADAR category can correspond to multiple DFG
subjects. Additional ODC license options are shared with the existing license vocabulary.

The XML parser preserves supported keyword and identifier attributes in canonical metadata. RDMO import
writes rights-holder names to the corrected `project/dataset/ipr/rightsholder` destination, retaining their
dataset and collection indices. Other label/name destinations remain unchanged. Import warns when GND
keyword identity, affiliation identity or rights-holder identity has no destination. Funder-ID import remains unsupported;
it never writes a persistent ID to `project/funder/id`. Publisher import remains unsupported. New export
paths retain the existing answer allocation and merge rules. Full identifier-preserving RDMO import is deferred.

Import destinations retain known-prefix precedence through RDMO's import APIs. Explicit full URIs bypass
fallback. Ambiguous custom-prefix Attribute or Option resolution reports a mapping issue and stages no
Value for that destination. Merge checks and collection/index allocation use the selected Attribute's
answers; another namespace's answers cannot suppress or advance an import. Subject Option deduplication
also follows identity. Reusable field strategies and explicit application profiles now support independent catalog mappings;
TF destination policies remain confined to the TF profile.

Tests import the supplied catalog into an isolated database and load the prototype's values with
their original coordinates and options. They exercise both providers, XML validation/download,
subject and source vocabularies, licenses, nested datasets, funding groups, and snapshot isolation.
The expected prototype output contains two labeled datasets, the first dataset's description,
three source entries (`Survey`, `Trial`, `Trial`), its CC-BY license, and shared keywords, funding,
and the Ancient Cultures subject retained as `Other` with its label.

## Observed draft metadata and gaps

On 2026-10-08 the user reported successful creation and opening of a RADAR dataset and
supplied its [downloaded descriptive XML](../tests/xml/RADAR_DATASET_DESCRIPTIVE_METADATA.xml).
The live RDMO answers included Web scraping, which is absent from the older prototype
project snapshot. A separate regression scenario adds that option to dataset 0 without
changing the original fixture.

The document preserves the expected title, acronym as an additional title, all three
keywords, Ancient Cultures subject label, resource description, four creation methods,
CC-BY licence, and DFG funding name, award number, and programme title. Comparison with
the saved prototype plus the confirmed extra method found no clear loss in those fields.

| Gap in the downloaded document | Mapping or source limitation at observation time |
| --- | --- |
| Identifier and scheme | No populated dataset publication PID in the prototype; no identifier is invented. |
| Creators | No established dataset-creator answers. Coordination and data-management names exist, but mapping them to creators or contributors is deferred. |
| Publishers | No publisher reader in the current RDMO mapping. The adapters support publishers when supplied in canonical metadata. |
| Production year | No agreed dataset production-date mapping. Project dates do not supply this value. |
| Resource type | Intentionally unset pending an agreed source; file formats are not resource types. |
| Rights holders | No established rights-holder-name answers in the prototype. |

These are the missing publication fields reported by the plugin's canonical completeness
check. Successful draft creation does not make the downloaded XML complete under the
bundled XSD: it lacks the required identifier and resource-type attribute, among other
publication fields. The tests retain these warnings and allow draft XML download.

Other absent fields include contributors, typed descriptions, language, software,
processing, geolocation, version, publication year, alternate/related identifiers, and
related information. Funding has no award URL or persistent funder identifier here.
Their absence alone does not demonstrate export loss: some lack populated established
source answers and others have deferred mappings. In particular, coordination/data-management
people and `project/dataset/usage_description` text are possible future mapping work,
not inferred creators, contributor roles, abstracts, or processing statements.

Regression tests remain offline and production mapping behavior is unchanged. The
[contract notes](radar-api-contract.md#observed-authenticated-draft-export) distinguish
the live descriptive-value evidence from the independently specified REST contract.
