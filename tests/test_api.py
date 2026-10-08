"""Contract shapes audited against public RADAR REST responses; see docs/radar-api-contract.md."""
import json
from copy import deepcopy
from pathlib import Path

from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.types import (
    Affiliation,
    Agent,
    Description,
    FundingReference,
    GeoLocation,
    Identifier,
    MappingIssue,
    RadarMetadata,
    Resource,
    Rights,
    Software,
    SubjectArea,
)


def full_metadata():
    return RadarMetadata(
        identifier=Identifier('10.1234/example', 'DOI'),
        alternate_identifiers=[Identifier('local-1', 'Local catalogue')],
        related_identifiers=[Identifier('10.1234/related', 'DOI', 'IsCitedBy')],
        creators=[Agent('Doe, Jane', 'Jane', 'Doe', 'Personal',
                        [Identifier('0000-0001', 'ORCID')],
                        [Affiliation('University', 'https://ror.org/example', 'ROR')])],
        contributors=[Agent('Example organization', name_type='Organizational',
                            affiliations=[Affiliation('Institute')], contributor_type='DataManager')],
        title='Dataset',
        additional_titles=['DATA', 'Alternative title'],
        descriptions=[Description('Abstract'), Description('Changes', 'VersionNotes')],
        keywords=['FAIR', 'Science'],
        publishers=[Agent('Repository'), Agent('University', identifiers=[Identifier('ror-1', 'ROR')])],
        production_year='2025',
        publication_year='2026',
        language='eng',
        subject_areas=[SubjectArea('Chemistry'), SubjectArea('Other', 'Interdisciplinary')],
        resource=Resource('Research data', 'Dataset'),
        geo_locations=[GeoLocation('Germany', 'Berlin', '52.5', '13.4'), GeoLocation(region='Brandenburg')],
        data_sources=[Resource('Survey results', 'Survey'), Resource('Unclassified source')],
        software=[Software('Viewer', 'Resource Viewing', '1.0', 'Alternative viewer', '2.0')],
        processing=['Cleaned', 'Aggregated'],
        rights=Rights('CC BY 4.0 Attribution', 'Attribution details'),
        rights_holders=[Agent('University'), Agent('Doe, Jane', identifiers=[Identifier('0000-0001', 'ORCID')])],
        related_information=['Project website'],
        funding_references=[FundingReference('Funder', Identifier('ror-2', 'ROR'),
                                             'ABC-123', 'https://example.test/award', 'Award title')],
        version='2.1',
        mapping_issues=[MappingIssue('test', 'Not serialized')],
    )


def test_full_api_payload_and_input_are_independent():
    metadata = full_metadata()
    original = deepcopy(metadata)
    expected = json.loads((Path(__file__).parent / 'fixtures' / 'radar-api-full.json').read_text())
    payload = to_api_payload(metadata)
    assert payload == expected
    assert metadata == original
    payload['processing']['dataProcessing'].append('Changed')
    assert metadata == original


def test_additional_titles_use_rest_container_and_value():
    assert to_api_payload(RadarMetadata(additional_titles=['DATA'])) == {
        'additionalTitles': {'additionalTitle': [{'value': 'DATA', 'additionalTitleType': 'OTHER'}]},
    }


def test_api_serialization_does_not_call_xml_adapter(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('REST must not serialize through XML')

    monkeypatch.setattr('rdmo_radar.metadata.xml.to_xml_payload', fail)
    assert to_api_payload(RadarMetadata(title='Draft', resource=Resource('Description'))) == {
        'title': 'Draft', 'resource': {'value': 'Description'},
    }
    assert to_api_payload(RadarMetadata()) == {}


def test_only_first_affiliation_is_serialized_without_mutating_metadata():
    metadata = RadarMetadata(creators=[Agent('Creator', affiliations=[Affiliation('First'), Affiliation('Second')])])
    assert to_api_payload(metadata)['creators']['creator'][0]['creatorAffiliation'] == {'value': 'First'}
    assert len(metadata.creators[0].affiliations) == 2
