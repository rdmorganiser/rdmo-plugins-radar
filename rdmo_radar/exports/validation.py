from functools import lru_cache
from pathlib import Path

import xmlschema

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


def get_radar_validation_errors(xml_data) -> tuple[str, ...]:
    """Return the unique RDDM schema violations found in an XML document."""
    reasons = (error.reason for error in get_radar_schema().iter_errors(xml_data))
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


def validate_radar_xml(xml_data):
    """Return the first RDDM schema violation, retained for compatibility."""
    return next(iter(get_radar_validation_errors(xml_data)), None)
