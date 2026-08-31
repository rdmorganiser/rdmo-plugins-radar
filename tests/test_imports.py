from types import SimpleNamespace
from xml.etree import ElementTree

from rdmo.domain.models import Attribute
from rdmo.options.models import Option

from rdmo_radar.imports.imports import RadarImport


def test_import_funder_identifier_uses_type_attribute():
    radar_import = RadarImport.__new__(RadarImport)
    radar_import.current_project = SimpleNamespace(values=SimpleNamespace(filter=lambda **kwargs: []))
    radar_import.root = ElementTree.fromstring('''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <fundingReferences>
            <fundingReference>
              <funderName>Example Funder</funderName>
              <funderIdentifier type="ROR">https://ror.org/123</funderIdentifier>
            </fundingReference>
          </fundingReferences>
        </radarDataset>
    ''')
    radar_import.ns_map = {'ns1': 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'}
    radar_import.values = []
    radar_import.get_attribute = lambda uri: Attribute(path=uri)
    ror_option = Option()
    radar_import.get_option = lambda uri: ror_option

    radar_import.process_funders()

    scheme_values = [value for value in radar_import.values if value.attribute.path.endswith('name_identifier_scheme')]
    assert len(scheme_values) == 1
    assert scheme_values[0].option is ror_option


def test_import_funder_identifier_without_type_does_not_default_to_orcid():
    radar_import = RadarImport.__new__(RadarImport)
    radar_import.current_project = SimpleNamespace(values=SimpleNamespace(filter=lambda **kwargs: []))
    radar_import.root = ElementTree.fromstring('''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <fundingReferences>
            <fundingReference>
              <funderName>Example Funder</funderName>
              <funderIdentifier>https://example.test/funder</funderIdentifier>
            </fundingReference>
          </fundingReferences>
        </radarDataset>
    ''')
    radar_import.ns_map = {'ns1': 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'}
    radar_import.values = []
    radar_import.get_attribute = lambda uri: Attribute(path=uri)
    radar_import.get_option = lambda uri: Option()

    radar_import.process_funders()

    assert not any(value.attribute.path.endswith('name_identifier_scheme') for value in radar_import.values)
