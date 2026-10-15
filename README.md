# rdmo-plugins-radar

This repo implements several plugins to connect [RDMO](https://github.com/rdmorganiser/rdmo) with [RADAR](https://www.radar-service.eu/):

* `rdmo_radar.exports.RadarExport`, which lets users download their RDMO datasets as RADAR-XML metadata files,
* `rdmo_radar.exports.RadarExportProvider`, which pushes RDMO datasets to RADAR using a browser OAuth flow,
* `rdmo_radar.exports.RadarCredentialsExportProvider`, which pushes them using local RADAR credentials,
* `rdmo_radar.imports.RadarImport`, which lets users import RADAR-XML metadata files (exported from RADAR) into RDMO.

The direct export can use either an [OAuth 2.0](https://oauth.net/2/) authorization-code flow or RADAR's JSON
token endpoint, depending on the client registered by RADAR support.


Setup
-----

These instructions use RDMO 2's project export/import interfaces. RDMO 3 frontend integration is deferred.

Install the plugin in your RDMO virtual environment using pip (directly from GitHub):

```bash
pip install git+https://github.com/rdmorganiser/rdmo-plugins-radar
```

Add the plugin package to `INSTALLED_APPS` so Django can discover its templates:

```python
INSTALLED_APPS += ['rdmo_radar']
```

For the `RadarExport`, add the plugin to `PROJECT_EXPORTS` in `config/settings/local.py`:

```python
PROJECT_EXPORTS += [
    ('radar-xml', _('as RADAR XML'), 'rdmo_radar.exports.RadarExport')
]
```

For direct exports an *App* has to be registered with RADAR. Please contact RADAR support for the necessary steps.
Configure the OAuth callback as `redirect_uri`; the credentials provider derives the tenant root URL required by
RADAR from this value:

```python
RADAR_PROVIDER = {
    'authentication_mode': 'oauth',
    'oauth_token_auth_method': 'client_secret_basic',
    'radar_url': 'https://test.radar-service.eu',
    'client_id': '',
    'client_secret': '',
    'redirect_uri': 'https://rdmo.example.com/services/oauth/radar/callback/'
}
```

The modes are:

* `oauth`: use `RadarExportProvider`, the browser authorization-code flow, and `redirect_uri`. This is the default
  for existing installations without an `authentication_mode` setting.
* `credentials`: use `RadarCredentialsExportProvider`. Users enter a local RADAR username and password. RDMO sends
  them directly to the RADAR token endpoint and does not store them. The bearer token stays in the session
  during the export workflow and is removed on success, cancellation, or authentication failure. Metadata,
  permission, and upstream errors preserve the export form and selections. The token request derives
  `https://rdmo.example.com/` from `redirect_uri`.

For OAuth, `oauth_token_auth_method` controls how RDMO authenticates the client at RADAR's token endpoint:

* `client_secret_basic` sends the client ID and secret using HTTP Basic authentication and remains the default when
  the setting is omitted.
* `client_secret_post` sends the client ID, secret, authorization code, grant type, and redirect URI together as
  form-encoded POST data.

Only select `client_secret_post` when it matches the RADAR client registration. Never log either request body.

Select the provider class from the setting when adding it to `PROJECT_EXPORTS`:

```python
radar_provider_class = {
    'oauth': 'rdmo_radar.exports.RadarExportProvider',
    'credentials': 'rdmo_radar.exports.RadarCredentialsExportProvider',
}[RADAR_PROVIDER.get('authentication_mode', 'oauth')]

PROJECT_EXPORTS += [
    ('radar', _('directly to RADAR'), radar_provider_class)
]
```

For the `RadarImport`, add the plugin to `PROJECT_IMPORTS` in `config/settings/local.py`:

```python
PROJECT_IMPORTS += [
    ('radar-xml', _('from RADAR XML'), 'rdmo_radar.imports.RadarImport')
]
```


### Mapping selection

Existing registrations and factories retain the Template Framework mapping. New explicit classes let
project-level and collection-based mappings coexist in one installation:

```python
PROJECT_EXPORTS += [
    ('radar-project-xml', _('as RADAR XML (project)'), 'rdmo_radar.exports.RadarProjectExport'),
    ('radar-tf-xml', _('as RADAR XML (Template Framework)'), 'rdmo_radar.exports.RadarTemplateFrameworkExport'),
]
```

The project mapping exports one record using `Project.title`, including projects without a catalog or
dataset Attributes. It leaves other metadata unset and reports missing required fields. It supplies no
import mapping or local result storage. The Template Framework mapping discovers entered dataset records,
preserves shared metadata and vocabulary mappings, and supports catalog-less flat markers. Empty dataset
collections produce no datasets. Nested records with the same local index have distinct selection keys.

For direct exports, select the corresponding registered class:

| Mapping | OAuth class | Credentials class |
| --- | --- | --- |
| Project | `rdmo_radar.exports.RadarProjectExportProvider` | `rdmo_radar.exports.RadarProjectCredentialsExportProvider` |
| Template Framework | `rdmo_radar.exports.RadarTemplateFrameworkExportProvider` | `rdmo_radar.exports.RadarTemplateFrameworkCredentialsExportProvider` |

For example:

```python
project_provider_class = {
    'oauth': 'rdmo_radar.exports.RadarProjectExportProvider',
    'credentials': 'rdmo_radar.exports.RadarProjectCredentialsExportProvider',
}[RADAR_PROVIDER.get('authentication_mode', 'oauth')]
PROJECT_EXPORTS += [('radar-project', _('directly to RADAR (project)'), project_provider_class)]
```

`RADAR_PROVIDER` configures authentication; the registered class selects the mapping. The existing
`RadarExport`, `RadarExportProvider`, `RadarCredentialsExportProvider`, and `RadarImport` paths remain
Template Framework entry points. `rdmo_radar.imports.RadarTemplateFrameworkImport` is an explicit equivalent.
There is no built-in project importer: arbitrary catalogs need an explicit destination mapping.

### Simple custom mapping

For a catalog with ordinary questions and no dataset collections, start with `RadarProjectExport`.
Write one function to read your Attributes and construct RADAR metadata. For this example, the catalog
defines Attributes with the URIs `https://example.org/terms/domain/research/title`,
`https://example.org/terms/domain/research/description`, and
`https://example.org/terms/domain/research/keywords`; its description question
explicitly asks for the dataset abstract, and its keywords question allows multiple text answers.
Save this complete example as `example_rdmo_plugin/exports.py` in an installed Python package:

```python
from dataclasses import replace

from rdmo_radar.exports import RadarProjectExport
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.metadata.types import Description, MappingResult, RadarMetadata


def read_metadata(context):
    description = context.get_text('https://example.org/terms/domain/research/description')
    return MappingResult(
        RadarMetadata(
            title=context.get_text('https://example.org/terms/domain/research/title') or context.project.title,
            descriptions=[Description(description)] if description else [],
            keywords=context.get_texts('https://example.org/terms/domain/research/keywords'),
        ),
        tuple(context.issues),
    )


class ExampleRadarExport(RadarProjectExport):
    mapping = replace(PROJECT_MAPPING, compute_metadata=read_metadata)
```

Register its dotted class path in your RDMO settings:

```python
from django.utils.translation import gettext_lazy as _

PROJECT_EXPORTS += [
    (
        'example-radar-xml',
        _('as RADAR XML (example-catalog)'),
        'example_rdmo_plugin.exports.ExampleRadarExport',
    ),
]
```

Questions and project Values refer to the same Attribute. For example, a Question with URI
`https://example.org/terms/questions/example-catalog/overview/metadata/title` can reference the Attribute
`https://example.org/terms/domain/research/title`; Values store answers through that Attribute's foreign
key. Another Question or catalog can reuse it. The Question URI identifies the questionnaire element,
while the Attribute URI is the shared domain reference. RDMO generates Attribute paths and URIs from
`key`, `parent`, and `uri_prefix`. Use existing shared Attributes when their meaning matches your field.
An Attribute path does not define a collection: that comes from catalog elements and Value coordinates.

The project exporter supplies one export record, prepared Value access, and the export workflow. You only
replace the metadata function. `Description` defaults to the RADAR `Abstract` type. The mapping uses your
explicitly chosen Attribute; it does not interpret `Project.description` as a dataset abstract. Missing
title answers fall back to `Project.title`. Incomplete metadata still produces warnings, and
`tuple(context.issues)` carries access diagnostics into the existing export presentation.

Full Attribute URIs are portable references between catalog exports and installations. Database IDs
identify installed Attribute objects. The convenience methods also accept an unambiguous path, so
`context.get_text('research/title')` remains shorthand for the example's full URI when no other prepared
Attribute shares that path. Their existing `path=` keyword is retained for compatibility with mappings.

The convenience methods accept a full Attribute URI, an unambiguous path, or an Attribute ID/model:

| Method | Use |
| --- | --- |
| `context.get_text(attribute)` | Read one text answer, or `None` when absent or conflicting. |
| `context.get_texts(attribute)` | Read distinct, nonempty text answers as a list. |
| `context.get_option(attribute, options)` | Translate a controlled answer using an explicit Option mapping. |
| `context.get_values(attribute)` | Read the underlying scoped RDMO Values when needed. |

For example, `context.get_option('research/language', {'https://example.org/options/language/en': 'eng'})`
uses a complete Option URI. If Attribute paths collide across namespaces, use the full Attribute URI;
ambiguous path access reports a mapping issue instead of combining answers.

The same metadata function can serve a direct export. Add this class to the example module:

```python
from rdmo_radar.exports import RadarProjectExportProvider


class ExampleRadarDirectExport(RadarProjectExportProvider):
    mapping = ExampleRadarExport.mapping
```

Register `example_rdmo_plugin.exports.ExampleRadarDirectExport` for OAuth exports. For credentials authentication,
use `RadarProjectCredentialsExportProvider` as the base class instead. Both use the same metadata function
and REST serializer; authentication remains configured through `RADAR_PROVIDER`. The project profile
supplies no local result storage or import mapping.

This preserves the original exporter's straightforward mapping style. It does not restore its specific
Template Framework field mappings: historical registrations still use that profile. More advanced catalogs
can customize discovery, scoping, imports, and persistence through the existing
[profile contracts and factory overrides](docs/architecture.md#mapping-profiles-and-datasets).

### Custom RADAR request payload

`get_datasets()` returns the datasets to export as `ExportDataset` objects. Each describes which RDMO
answers will become one RADAR dataset: the project mapping exports the whole project as one dataset,
while the Template Framework mapping exports one dataset per dataset collection entry. Its `key` and
`label` supply the export form choices, and its `scope` identifies the source answers. RDMO provides the
Project, Values, and collection coordinates; `ExportDataset` belongs to this plugin. `get_payload(dataset)`
then builds the REST request for the selected dataset.

For direct REST exports, override `get_payload(dataset)` to define the complete request body.
You can keep the project-level dataset and export workflow without writing a metadata mapping.
Save this example as `example_rdmo_plugin/exports.py`:

```python
import time

from rdmo_radar.exports import RadarProjectExportProvider


class ExampleRadarExportProvider(RadarProjectExportProvider):
    def get_payload(self, dataset):
        context = self.get_context(dataset)
        timestamp = int(time.time() * 1000)
        return {
            'technicalMetadata': {
                'retentionPeriod': 10,
                'archiveDate': timestamp,
                'publishDate': timestamp,
                'responsibleEmail': self.request.user.email,
                'schema': {'key': 'RDDM', 'version': '9.3'},
            },
            'descriptiveMetadata': {
                'title': (
                    context.get_text('https://example.org/terms/domain/research/title')
                    or self.project.title
                ),
                'keywords': {
                    'keyword': [
                        {'value': keyword}
                        for keyword in context.get_texts('https://example.org/terms/domain/research/keywords')
                    ],
                },
            },
        }
```

Register the provider in your RDMO settings:

```python
from django.utils.translation import gettext_lazy as _

PROJECT_EXPORTS += [
    (
        'example-radar-direct',
        _('directly to RADAR (example-catalog)'),
        'example_rdmo_plugin.exports.ExampleRadarExportProvider',
    ),
]
```

For credentials authentication, use `RadarProjectCredentialsExportProvider` as the base class instead.
Both providers inherit authentication, workspace selection, session handling, and confirmed-result
handling; configure authentication through `RADAR_PROVIDER`. The project profile supplies one dataset
and intentionally disables local result storage. Advanced profiles can customize discovery and storage
independently of this payload hook.

`get_context(dataset)` returns a `ProjectReadContext`, which provides safe Attribute access to prepared
project Values within the selected profile's scope. The hook runs once for the selected dataset on submission.
OAuth saves that request and replays it after authorization without calling the hook again.
Canceling clears the pending request. Dataset creation requires a complete saved export context, and a
confirmed RADAR ID remains available even if its local destination can no longer be recovered.

The returned dictionary goes directly to the REST transport. Supply the complete body, including
`technicalMetadata` and `descriptiveMetadata`; the plugin checks only that it is a JSON-serializable
dictionary. Preparation errors are shown before submission. Field mapping and technical defaults are
supplied by the default hook, when called, rather than after your override returns. To retain its defaults
and change a field, use this alternative implementation:

```python
def get_payload(self, dataset):
    context = self.get_context(dataset)
    payload = super().get_payload(dataset)
    payload['descriptiveMetadata']['title'] = (
        context.get_text('https://example.org/terms/domain/research/title')
        or self.project.title
    )
    return payload
```

Profile-derived mapping warnings are automatically disabled when `get_payload()` is overridden, so
the form does not report missing fields from a mapping you bypassed. Set `show_mapping_warnings = True`
on your subclass when those warnings still describe your payload, or `False` to disable them explicitly.
The default `None` selects this automatic behavior. You can also override `get_mapping_warnings()` to
provide your own diagnostics; payload hooks are never called to generate warnings or form previews.
Custom payloads do not inherit canonical completeness checks, and diagnostics from custom context reads
are available through `context.issues` for your own warning implementation.

This hook serves direct REST exports. Use a `RadarMetadata` mapping when the same interpretation should
also support XML export.


Usage
-----

The plugins appear as export/import options on the RDMO project overview.

The export provider fetches the available RADAR workspaces, and then lets the user choose
which dataset should be created in which workspace. The plugin creates a PENDING RADAR dataset using RDDM 9.3.
Incomplete descriptive metadata is accepted at this stage and can be completed in the RADAR interface before the
dataset is archived or published. The actual data can also be uploaded through the RADAR interface.

The downloadable RADAR XML export also targets RDDM 9.3. Every generated XML file is checked against the bundled
official schema. Valid exports download immediately. If required metadata is missing or the XML violates the schema,
RDMO shows the warnings per file and lets the user download the ZIP anyway for testing with RADAR. Only errors that
prevent XML generation block the download.

The exporter supports the DMP4NFDI 2.0.0 catalog and the 2026 Template Framework mapping, including
dataset collection labels, nested answers, DFG subject areas, creation methods, licenses, and
funding. An explicit dataset title takes precedence over its collection label. Mapping warnings
identify answers that need completion in RADAR. See [the mapping documentation](docs/metadata-mapping.md)
for supported fields and deferred decisions.

File/media formats do not determine RADAR resource type. Resource type remains unset until users complete
it in RADAR. RADAR XML import also leaves the file-format field untouched when importing resource types.

Direct exports use an independent REST adapter, audited against populated public RADAR API responses.
See [the REST contract references](docs/radar-api-contract.md). The credentials provider uses a small HTTP
client with `RADAR_PROVIDER['request_timeout']` (default: 30 seconds) on each request. Metadata rejection
and missing workspace permissions are reported without requesting another login. Creation is never retried
automatically; if the outcome is uncertain, check RADAR for an existing draft before retrying.

OAuth continues to use RDMO's `OauthProviderMixin`. Its current transport does not expose timeout or
request-injection hooks and logs some upstream response bodies itself. Improving those hooks and logs,
and adding catalog-aware value scopes to RDMO core, are separate upstream follow-ups. Plugin-owned
error handlers log only HTTP status. The client uses standard Requests exceptions; adapters show translated
messages based on status and workflow, without displaying raw exception text or response bodies.

The registered adapters assemble the services through small factories. XML export handles current projects
and snapshots; direct export separates payload preparation, the remote request, and confirmed-result storage.
OAuth callbacks use the registered mapping's persistence hook and captured dataset scope without preparing
project answers again. Both direct providers build
the dataset link from the RADAR instance used for creation. If creation succeeds but local storage fails, RDMO
shows the confirmed dataset link so users can inspect it before attempting another export.
When a profile omits storage, confirmed creation succeeds without writing RDMO Values.

Import retains RDMO's preview and checked-value save workflow; the mapping service stages unsaved Values.
`ProjectWriteContext` resolves Attributes and Options through RDMO's import API, merges existing answers,
and collects diagnostics while staging Values. `ProjectReadContext` provides scoped access to prepared
project Values for export mappings.
Template Framework imports resolve short Attribute and Option paths using the official default
`https://rdmorganiser.github.io/terms/` and RDMO's model URI builders. Full URIs resolve exactly. When an
official URI is absent, a unique installed-path match can supply a custom namespace; ambiguous matches
are reported without staging. This plugin default is independent of Django's `DEFAULT_URI_PREFIX` setting.
See [the architecture documentation](docs/architecture.md) for service customization and verification.

For diagnostics, RADAR administrators can use the API endpoints
`GET /radar/api/datasets/{id}/metadata/validate` and `GET /radar/api/schemas/{contractId}/RDDM/9.3`. The plugin does
not call either endpoint during a normal direct export because newly created drafts are intentionally allowed to be
incomplete.


OAuth troubleshooting
---------------------

If RADAR support identifies an `invalid_client` token-exchange failure after browser login, verify with them
that the client is enabled for the authorization-code endpoints below `/radar-backend/oauth/`, that the token
endpoint expects HTTP Basic client authentication, and that the configured secret belongs to that OAuth client.
Successful use of the separate `/radar/api/tokens` endpoint does not by itself confirm the OAuth registration.

RADAR must register the complete callback URL for every tenant, including the callback path and trailing slash:

```text
https://rdmo.example.com/services/oauth/radar/callback/
```

The callback must use the same scheme, hostname, and port as the RDMO instance where the export starts.
For a localhost debug server, configure a localhost callback and have RADAR register it, or start the export
on the deployment named in the configured callback. The plugin checks the callback origin before OAuth
authorization and shows a configuration error if it differs. Behind a reverse proxy, Django must see the
public request scheme and host for this check to succeed.

OAuth state and the pending export belong to the initiating browser session. A callback sent to another
deployment, or opened after the session expires, cannot resume that export. RDMO core's callback view
currently returns HTTP 500 when no provider has OAuth state in the session, before the plugin's callback
handler runs. Handling such incoming callbacks gracefully requires an upstream RDMO change; the plugin's
origin check prevents the localhost-to-staging redirect from being started.

Do not replace this callback with the tenant root URL. The callback view validates the OAuth state, exchanges the
authorization code, and resumes the pending export. When checking a deployed secret, compare its length and a
fingerprint rather than writing the secret itself to logs or command output.
