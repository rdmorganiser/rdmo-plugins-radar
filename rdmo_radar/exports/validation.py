from functools import lru_cache
from pathlib import Path

import xmlschema
from xmlschema.validators.exceptions import XMLSchemaValidationError

SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / 'schemas'


@lru_cache(maxsize=1)
def get_radar_schema():
    return xmlschema.XMLSchema(
        str(SCHEMA_DIRECTORY / 'RadarDataset.xsd'),
        locations={
            'http://purl.org/dc/terms/': str(SCHEMA_DIRECTORY / 'dcterms.xsd'),
            'http://purl.org/dc/elements/1.1/': str(SCHEMA_DIRECTORY / 'dc.xsd'),
            'http://purl.org/dc/dcmitype/': str(SCHEMA_DIRECTORY / 'dcmitype.xsd'),
            'http://www.w3.org/XML/1998/namespace': str(SCHEMA_DIRECTORY / 'xml.xsd')
        },
        allow='local'
    )


def validate_radar_xml(xml_data):
    try:
        get_radar_schema().validate(xml_data)
    except XMLSchemaValidationError as error:
        return error.reason
    return None
