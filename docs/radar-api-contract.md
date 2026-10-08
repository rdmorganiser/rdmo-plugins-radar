# RADAR REST contract references

The REST adapter is independent of the XML renderer. The full expected payload in
`tests/fixtures/radar-api-full.json` is hand-written with synthetic values, using the
following public RADAR GET responses inspected on 2026-10-07. Tests read this local
fixture and do not contact RADAR.

| Reference | Audited fields |
| --- | --- |
| [DynaBench dataset](https://www.radar-service.eu/radar/api/datasets/NjsVxNVRVtzvNfcm) | Identifier object; creators/contributors and single affiliation objects; descriptions, keywords, language, publishers, related identifiers, resource, rights, rights holders, subjects. |
| [Climate dataset](https://www.radar-service.eu/radar/api/datasets/wpc999nf5v4d73qa) | Additional-title container with `value` entries; data sources; software container, repeated software-name objects, and alternative software/version objects. |
| [LandKlif dataset](https://www.radar-service.eu/radar/api/datasets/kVwdJzhvGiZoyRBe) | Funding reference and funder identifier; geolocation country; related-information container. |
| [Simulation dataset](https://www.radar-service.eu/radar/api/datasets/nsuukgnw98bwpzda) | Processing container with `dataProcessing` string list. |
| [FoDaSi dataset](https://www.radar-service.eu/radar/api/datasets/zugqaqc5fn1xssay) | Alternate identifiers and case-preserving, free-text `alternateIdentifierType`. |

The public listing `/radar/api/datasets?rows=100` also confirms unadorned publisher
and affiliation names are `value` objects and geolocation coordinates are JSON numbers.
Missing draft fields are omitted. `alternateIdentifierType` and `relatedInformationType`
are free text; controlled enums use the existing API enum conversion.

RDDM 9.3 permits one affiliation per creator/contributor. Both output adapters retain
the first canonical affiliation, while leaving the canonical list unchanged. REST's
name, software, processing, and identifier structures must not be copied from the
XML renderer's intermediate dictionary.

The [official API documentation](https://radar.products.fiz-karlsruhe.de/en/radarfeatures/radar-api)
documents request endpoints and the RDDM 9.3 technical metadata envelope. These public
response references establish populated shapes; local tests do not perform live
authenticated draft creation.

## Observed authenticated draft export

On 2026-10-08 the user reported that export successfully created and opened a RADAR
dataset after workspace discovery switched to the bare `/radar/api/workspaces` endpoint.
The user downloaded its descriptive metadata and supplied the unchanged document at
[RADAR_DATASET_DESCRIPTIVE_METADATA.xml](../tests/xml/RADAR_DATASET_DESCRIPTIVE_METADATA.xml).
They confirmed that RDMO answers had changed since the saved prototype: the observed
dataset includes the additional Web scraping creation method.

Offline regression tests reconstruct this source scenario by adding catalog option
`dfg_new_data/dfg-nd_11` to dataset 0 in a separate fixture. They compare generated XML
structurally with the downloaded document and check both providers against an explicit,
hand-written REST expectation. The original prototype remains unchanged.

This evidence confirms preservation of the document's populated descriptive values;
the downloaded XML does not independently establish JSON wire shapes or publication
readiness. The draft remains incomplete under the bundled XSD. See the
[observed metadata gap report](metadata-mapping.md#observed-draft-metadata-and-gaps).
