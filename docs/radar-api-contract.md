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

## Typed identity extension (2026-10-28)

The fixture now also specifies `schemeURI` for ORCID/ROR name identifiers, affiliations, publishers,
rights holders and funder identifiers. These additions and the typed GND keyword expectations are based
on the bundled RDDM 9.3 XSD, the official
[metadata documentation](https://radar.products.fiz-karlsruhe.de/sites/default/files/radar/docs/info/RADAR_Metadaten_Dokumentation_v9.3.pdf),
and the RADAR demo's `resources/RadarDatasetExample-correction.xml`. That example references schema 9.2;
the bundled 9.3 XSD remains the offline XML validation reference. The API page and demo JSON examples do
not independently verify every populated REST field. These changes have **not** been verified through
an authenticated test-draft round trip.

The independent REST expectations include:

```json
{
  "keywords": {
    "keyword": [
      {"value": "Free text"},
      {"value": "Term", "keywordScheme": "GND", "schemeURI": "https://d-nb.info/gnd/",
       "valueURI": "https://d-nb.info/gnd/4079154-3", "classificationCode": "4079154-3"}
    ]
  },
  "publishers": {
    "publisher": [
      {"value": "Institute", "nameIdentifierScheme": "ROR",
       "nameIdentifier": "https://ror.org/0387prb75", "schemeURI": "https://ror.org/"}
    ]
  },
  "fundingReferences": {
    "fundingReference": [
      {"funderName": "Funder", "funderIdentifier": {
        "value": "https://ror.org/0387prb75", "type": "ROR", "schemeURI": "https://ror.org/"
      }}
    ]
  }
}
```

Creator/contributor `nameIdentifier` remains a list of objects with `value`, `nameIdentifierScheme`
and optional `schemeURI`. Their single affiliation object uses `value`, `affiliationIdentifier`,
`affiliationIdentifierScheme` and optional `schemeURI`. Rights-holder entries use the same named-value
shape as publishers. Free-text affiliation schemes retain their case; only controlled enums are converted.
TS4NFDI and ontology fields are outside this extension.

### Test-draft verification procedure

Use a separately configured RADAR test account and workspace. Create a pending draft through each REST
provider with the populated identity cases above, an ORCID creator, a ROR affiliation and an identified
rights holder. Read the dataset JSON and download its descriptive XML. Compare the names, identifier
values, schemes and scheme URIs, validate the XML, and confirm that each funder retains its own grant
fields. Include a free-text entry for each applicable field. Record the test-system date and observed
responses here after running the procedure. Do not publish or archive the draft; handle its cleanup
through the test account's ordinary workflow. Automated tests remain offline and never run this procedure.

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
