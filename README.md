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
and sharing RADAR's local answer index with RDMO core, are separate upstream follow-ups. Plugin-owned
client diagnostics log only operation, HTTP status, recognized error codes, and error category.

For diagnostics, RADAR administrators can use the API endpoints
`GET /radar/api/datasets/{id}/metadata/validate` and `GET /radar/api/schemas/{contractId}/RDDM/9.3`. The plugin does
not call either endpoint during a normal direct export because newly created drafts are intentionally allowed to be
incomplete.


OAuth troubleshooting
---------------------

If the browser login returns to RDMO but the token exchange fails with `invalid_client`, verify with RADAR support
that the client is enabled for the authorization-code endpoints below `/radar-backend/oauth/`, that the token
endpoint expects HTTP Basic client authentication, and that the configured secret belongs to that OAuth client.
Successful use of the separate `/radar/api/tokens` endpoint does not by itself confirm the OAuth registration.

RADAR must register the complete callback URL for every tenant, including the callback path and trailing slash:

```text
https://rdmo.example.com/services/oauth/radar/callback/
```

Do not replace this callback with the tenant root URL. The callback view validates the OAuth state, exchanges the
authorization code, and resumes the pending export. When checking a deployed secret, compare its length and a
fingerprint rather than writing the secret itself to logs or command output.
