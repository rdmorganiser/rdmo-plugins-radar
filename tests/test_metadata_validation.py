import pytest

from rdmo_radar.exports import RadarExportProvider
from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.metadata.types import Agent, Identifier, RadarMetadata, Resource, Rights, SubjectArea
from rdmo_radar.metadata.validation import missing_required_fields

from .helpers import complete_metadata


def test_empty_metadata_reports_all_required_paths_in_order():
    assert missing_required_fields(RadarMetadata()) == (
        'identifier', 'identifier.identifierType', 'creators.creator', 'title',
        'publishers.publisher', 'productionYear', 'subjectAreas.subjectArea',
        'resource.value', 'resource.resourceType', 'rights.controlledRights', 'rightsHolders.rightsHolder',
    )


@pytest.mark.parametrize(('changes', 'missing'), [
    ({'identifier': Identifier('', None)}, ('identifier', 'identifier.identifierType')),
    ({'creators': [Agent('')]}, ('creators.creator',)),
    ({'publishers': [Agent('')]}, ('publishers.publisher',)),
    ({'subject_areas': [SubjectArea('')]}, ('subjectAreas.subjectArea',)),
    ({'resource': Resource('Description')}, ('resource.resourceType',)),
    ({'rights': Rights('')}, ('rights.controlledRights',)),
    ({'rights_holders': [Agent('')]}, ('rightsHolders.rightsHolder',)),
])
def test_canonical_checks_validate_content_not_only_containers(changes, missing):
    assert missing_required_fields(complete_metadata(**changes)) == missing


def test_rest_provider_does_not_inherit_xml_exporter():
    provider = RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarExportProvider')
    assert not isinstance(provider, RadarExport)
    assert not hasattr(provider, 'prepare_files')


def test_xml_computes_metadata_once_per_dataset(monkeypatch):
    export = RadarExport('radar-xml', 'RADAR', 'rdmo_radar.exports.RadarExport')
    export.get_dataset_indices = lambda: [0]
    export.get_dataset_title = lambda index: 'Dataset'
    calls = []

    def compute(index):
        calls.append(index)
        return complete_metadata()

    export.compute_metadata = compute
    assert not export.prepare_files()[0].has_warnings
    assert calls == [0]


def test_rest_warnings_do_not_use_xml_adapter(monkeypatch):
    provider = RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarExportProvider')
    provider.get_dataset_indices = lambda: [0]
    provider.compute_metadata = lambda index: complete_metadata(resource=Resource('Description'))
    monkeypatch.setattr('rdmo_radar.metadata.xml.to_xml_payload', lambda metadata: pytest.fail('XML called'))
    assert provider.get_mapping_warnings() == [{'title': 'Dataset', 'issues': [], 'missing': ['Resource type']}]
