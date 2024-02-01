# ruff: noqa: F821
PROJECT_EXPORTS += [
    ('radar-xml', _('as RADAR XML'), 'rdmo_radar.exports.RadarExport')
]
PROJECT_IMPORTS += [
    ('radar', _('from RADAR XML'), 'rdmo_radar.imports.RadarImport')
]
PROJECT_EXPORTS += [
    ('radar', _('directly to RADAR'), 'rdmo_radar.exports.RadarExportProvider')
]
