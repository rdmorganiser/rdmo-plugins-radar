"""Safe RADAR protocol and export-operation errors."""


class RadarProtocolError(Exception):
    def __init__(self):
        super().__init__('RADAR returned an invalid response.')


class UnsupportedImportMapping(ValueError):
    """An explicitly selected mapping has no RADAR-to-RDMO staging implementation."""


class ExportStoreError(Exception):
    def __init__(self, set_index: int | str, radar_id: str, radar_url: str):
        self.set_index = set_index
        self.radar_id = radar_id
        self.radar_url = radar_url
        super().__init__('RADAR creation succeeded, but the export result could not be stored locally.')


class XmlExportError(Exception):
    def __init__(self, file_name: str):
        self.file_name = file_name
        super().__init__(f'RADAR XML export could not generate "{file_name}".')
