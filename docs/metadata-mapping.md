# RADAR 9.3 metadata mapping

This document accompanies `Mapping_radar-plugin_dmp-tf.xlsx - [neu]Mapping RADAR-RDMO.csv`.
Only mappings confirmed in the task-force column are implemented. The plugin does not infer a
mapping from older plugin fields: populated RDDM fields without a confirmed target are reported as
mapping issues during import, and missing required fields block the standalone XML export.

The internal `RadarMetadata` model uses RDDM 9.3 XML spellings such as `DOI`, `Dataset`, and
`IsCitedBy`. RDMO option paths and REST enum spellings belong exclusively to their adapters.
`project/dataset/id` is read only as a pre-migration dataset-set marker. It never supplies the
RDDM title or identifier.

| RDDM field | Confirmed RDMO mapping | Export | Import |
| --- | --- | --- | --- |
| Identifier | `project/dataset/data_publication_pid`; scheme from `project/dataset/pids/system` | yes, when present | yes |
| Creators | `project/dataset/creator/*` | yes | yes |
| Title | `project/dataset/title` | yes | yes |
| Subject areas | `project/research_field/title` | yes | merge by option path |
| Resource | `project/dataset/description` plus `project/dataset/format` | yes | yes |
| Rights | `project/dataset/sharing/conditions` | yes | yes |
| Rights holders | `project/dataset/ipr/owner/name` | yes | yes |
| Additional title | `project/acronym` | yes | preserve an existing differing acronym |
| Keywords | `project/research_question/keywords` | yes | merge and deduplicate |
| Contributors | `project/partner/*` | role exported as `Other` | merge by ORCID, then name |
| Language | `project/dataset/language` | yes | yes |
| Geolocation | `project/dataset/usage_technology/geo_location` | region only | first region only; report other coordinates |
| Data sources | `project/dataset/creation_methods` | yes when a RADAR detail is known | yes |
| Processing | `project/dataset/method` | yes | yes |
| Funding references | `project/funder/name`, `grant_nr`, and programme fields | yes | merge by identifier/name; `id` remains a set marker |

The following RDDM fields currently have no confirmed generic RDMO target: alternate identifiers,
related identifiers, descriptions, publishers, production year, publication year, software, related
information, version, persistent funder identifiers, and contributor roles other than `Other`.
Imports preserve the rest of the document and report these fields instead of guessing. In particular,
`project/funder/id` is not treated as a persistent funder identifier.

Standalone XML and REST intentionally have different completion policies. XML generation checks the
required RDDM fields before running XSD validation and returns a readable error if they are missing.
The REST provider remains permissive so RADAR can accept and complete a draft dataset.
