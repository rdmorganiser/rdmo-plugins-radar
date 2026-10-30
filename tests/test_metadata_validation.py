import pytest

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from rdmo_radar.exports import RadarTemplateFrameworkCredentialsExportProvider as RadarCredentialsExportProvider
from rdmo_radar.exports import RadarTemplateFrameworkExportProvider as RadarExportProvider
from rdmo_radar.exports.exports import RadarTemplateFrameworkExport as RadarExport
from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import get_radar_validation_errors
from rdmo_radar.mappings import ExportDataset
from rdmo_radar.mappings.template_framework.fields import FUNDING
from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.fields import read_funding
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.types import (
    FundingReference,
    Identifier,
    MappingResult,
    PersonOrOrganization,
    RadarMetadata,
    Resource,
    Rights,
    SubjectArea,
)
from rdmo_radar.metadata.validation import missing_required_fields
from rdmo_radar.metadata.xml import to_xml_payload

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
    provider = configure_service(
        RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarTemplateFrameworkExportProvider')
    )
    assert not isinstance(provider, RadarExport)
    assert not hasattr(provider, 'prepare_files')


def test_xml_computes_metadata_once_per_dataset(monkeypatch):
    export = configure_service(RadarExport('radar-xml', 'RADAR', 'rdmo_radar.exports.RadarTemplateFrameworkExport'))
    export.get_datasets = lambda: [ExportDataset('0', 'Dataset', {'set_index': 0})]
    calls = []

    def compute(context):
        calls.append(context.set_index)
        return MappingResult(complete_metadata())

    export.get_service().mapping = compute
    assert not export.prepare_files()[0]['has_warnings']
    assert calls == [0]


def test_rest_warnings_do_not_use_xml_adapter(monkeypatch):
    provider = configure_service(
        RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarTemplateFrameworkExportProvider')
    )
    provider.get_datasets = lambda: [ExportDataset('0', 'Dataset', {'set_index': 0})]
    provider.get_service().mapping = lambda context: MappingResult(complete_metadata(resource=Resource('Description')))
    monkeypatch.setattr('rdmo_radar.metadata.xml.to_xml_payload', lambda metadata: pytest.fail('XML called'))
    assert provider.get_mapping_warnings() == [{
        'dataset_key': '0', 'title': 'Dataset', 'issues': (), 'missing': ['Resource type'],
    }]


def test_partial_funding_is_preserved_with_a_missing_name_diagnostic():
    path = 'project/funder/grant_nr'
    answer = Value(attribute=Attribute(path=path), text='AWARD-42', set_index=7)
    context = ProjectReadContext({path: [answer]}, {}, provenance=[])
    funding = read_funding(context, sources=FUNDING, target='funding_references')
    assert funding == [FundingReference(award_number='AWARD-42')]
    assert any('no funder name' in issue.reason for issue in context.issues)
    assert any(
        a.outcome == 'empty' and any(s.value is answer for s in a.sources) and 'no funder name' in a.reason
        for a in context.provenance
    )
    metadata = complete_metadata(funding_references=funding)
    assert missing_required_fields(metadata) == ('fundingReferences.fundingReference[0].funderName',)
    assert to_api_payload(metadata)['fundingReferences']['fundingReference'] == [{'awardNumber': 'AWARD-42'}]
    assert get_radar_validation_errors(RadarExportRenderer().render(to_xml_payload(metadata)))


@pytest.mark.parametrize(
    'provider_class',
    [
        RadarCredentialsExportProvider,
        RadarExportProvider,
        RadarExport,
    ],
)
def test_missing_funder_name_is_visible_in_every_export_without_blocking_drafts(provider_class):
    provider = configure_service(
        provider_class(
            'review',
            'Review',
            f'{provider_class.__module__}.{provider_class.__name__}',
        )
    )
    dataset = ExportDataset('0', 'Dataset', {'set_index': 0})
    provider.get_datasets = lambda: [dataset]
    provider.get_service().mapping = lambda context: MappingResult(
        complete_metadata(
            funding_references=[
                FundingReference('Named funder'),
                FundingReference(award_number='AWARD-42'),
            ]
        )
    )
    if provider_class is RadarExport:
        result = provider.prepare_files()[0]
        assert {
            'path': 'fundingReferences.fundingReference[1].funderName',
            'label': 'Funder name (funding reference 2)',
        } in result['missing_fields']
        assert result['xml_data']
    else:
        warnings = provider.get_mapping_warnings()
        assert warnings[0]['missing'] == ['Funder name (funding reference 2)']
        payload = provider.get_service().compute_payload(dataset, 'user@example.test').payload
        assert payload['descriptiveMetadata']['fundingReferences']['fundingReference'][1]['awardNumber'] == 'AWARD-42'
