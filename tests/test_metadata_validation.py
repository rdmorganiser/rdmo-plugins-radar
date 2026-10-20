import pytest

from rdmo_radar.exports import RadarExportProvider
from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.mappings import ExportDataset
from rdmo_radar.metadata.types import (
    Identifier,
    MappingResult,
    PersonOrOrganization,
    RadarMetadata,
    Resource,
    Rights,
    SubjectArea,
)
from rdmo_radar.metadata.validation import missing_required_fields

from .helpers import complete_metadata, configure_service


def test_empty_metadata_reports_all_required_paths_in_order():
    assert missing_required_fields(RadarMetadata()) == (
        'identifier', 'identifier.identifierType', 'creators.creator', 'title',
        'publishers.publisher', 'productionYear', 'subjectAreas.subjectArea',
        'resource.value', 'resource.resourceType', 'rights.controlledRights', 'rightsHolders.rightsHolder',
    )


@pytest.mark.parametrize('changes, missing', [
    ({'identifier': Identifier('', None)}, ('identifier', 'identifier.identifierType')),
    ({'creators': [PersonOrOrganization('')]}, ('creators.creator',)),
    ({'publishers': [PersonOrOrganization('')]}, ('publishers.publisher',)),
    ({'subject_areas': [SubjectArea('')]}, ('subjectAreas.subjectArea',)),
    ({'resource': Resource('Description')}, ('resource.resourceType',)),
    ({'rights': Rights('')}, ('rights.controlledRights',)),
    ({'rights_holders': [PersonOrOrganization('')]}, ('rightsHolders.rightsHolder',)),
])
def test_canonical_checks_validate_content_not_only_containers(changes, missing):
    assert missing_required_fields(complete_metadata(**changes)) == missing


def test_rest_provider_does_not_inherit_xml_exporter():
    provider = configure_service(RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarExportProvider'))
    assert not isinstance(provider, RadarExport)
    assert not hasattr(provider, 'prepare_files')


def test_xml_computes_metadata_once_per_dataset(monkeypatch):
    export = configure_service(RadarExport('radar-xml', 'RADAR', 'rdmo_radar.exports.RadarExport'))
    export.get_datasets = lambda: [ExportDataset('0', 'Dataset', {'set_index': 0})]
    calls = []

    def compute(context):
        calls.append(context.set_index)
        return MappingResult(complete_metadata())

    export.get_service().mapping = compute
    assert not export.prepare_files()[0]['has_warnings']
    assert calls == [0]


def test_rest_warnings_do_not_use_xml_adapter(monkeypatch):
    provider = configure_service(RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarExportProvider'))
    provider.get_datasets = lambda: [ExportDataset('0', 'Dataset', {'set_index': 0})]
    provider.get_service().mapping = lambda context: MappingResult(complete_metadata(resource=Resource('Description')))
    monkeypatch.setattr('rdmo_radar.metadata.xml.to_xml_payload', lambda metadata: pytest.fail('XML called'))
    assert provider.get_mapping_warnings() == [{'title': 'Dataset', 'issues': (), 'missing': ['Resource type']}]
