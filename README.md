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
  them directly to the RADAR token endpoint, does not store them, and retains the bearer token only for that single
  export. The token request derives `https://rdmo.example.com/` from `redirect_uri`.

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
    ('radar', _('from RADAR XML'), 'rdmo_radar.imports.RadarImport')
]
```


Usage
-----

The plugins appear as export/import options on the RDMO project overview.

The export provider fetches the available RADAR workspaces, and then lets the user choose
which dateset should be archived in which workspace. The plugin creates a RADAR datasets.
The actual data can be uploaded through the RADAR interface.
