# rdmo-plugins-radar

This repo implements several plugins to connect [RDMO](https://github.com/rdmorganiser/rdmo) with [RADAR](https://www.radar-service.eu/):

* `rdmo_radar.exports.RadarExport`, which lets users download their RDMO datasets as RADAR-XML metadata files,
* `rdmo_radar.exports.RadarExportProvider`, which lets push their RDMO datasets directly to RADAR,
* `rdmo_radar.imports.RadarImport`, which lets users import RADAR-XML metadata files (exported from RADAR) into RDMO.

The `RadarExportProvider` plugin uses [OAUTH 2.0](https://oauth.net/2/), so that users use their respective accounts in both systems.


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

For the `RadarExportProvider` an *App* has to be registered with RADAR. Please contact the RADAR support for the nessesary steps. The `radar_url`, the `client_id`, the `client_secret`, and the `redirect_uri` need to be configured in `config/settings/local.py`, e.g. for the RADAR test service:

```python
RADAR_PROVIDER = {
    'radar_url': 'https://test.radar-service.eu',
    'client_id': '',
    'client_secret': '',
    'redirect_uri': 'https://rdmo.example.com/services/oauth/radar/callback/'
}
```

Then, add the plugin to `PROJECT_EXPORTS` in `config/settings/local.py`:

```python
PROJECT_EXPORTS += [
    ('radar', _('directly to RADAR'), 'rdmo_radar.exports.RadarExportProvider')
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

The plugins apear as export/import options on the RDMO project overview.

The export provider fetches the available RADAR workspaces, and then lets the user choose
which dateset should be archived in which workspace. The plugin creates a RADAR datasets.
The actual data can be uploaded through the RADAR interface.
