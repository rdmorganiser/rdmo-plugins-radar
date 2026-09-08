from types import SimpleNamespace
from xml.etree import ElementTree

from rdmo.domain.models import Attribute
from rdmo.options.models import Option

from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import validate_radar_xml
from rdmo_radar.imports.imports import RadarImport
from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.constants import XMLVocabulary
from rdmo_radar.metadata.types import (
    Affiliation,
    Agent,
    Description,
    GeoLocation,
    Identifier,
    RadarMetadata,
    Resource,
    Rights,
    SubjectArea,
)
from rdmo_radar.metadata.xml import missing_required_fields, parse_xml, to_xml_payload


def make_export():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.get_set = lambda *args, **kwargs: []
    export.get_values = lambda *args, **kwargs: []
    export.get_list = lambda *args, **kwargs: []
    export.get_text = lambda *args, **kwargs: None
    export.get_option = lambda *args, **kwargs: None
    return export


def make_import(xml):
    radar_import = RadarImport.__new__(RadarImport)
    radar_import.current_project = SimpleNamespace(
        catalog=object(),
        values=SimpleNamespace(filter=lambda **kwargs: []),
    )
    radar_import.root = ElementTree.fromstring(xml)
    radar_import.values = []
    paths = {
        'project/dataset/title',
        'project/dataset/data_publication_pid',
        'project/dataset/pids/system',
        'project/dataset/description',
        'project/dataset/format',
        'project/dataset/creation_methods',
        'project/funder/id',
        'project/funder/name',
        'project/funder/grant_nr',
        'project/research_question/keywords',
        'project/partner/name',
        'project/partner/given_name',
        'project/partner/family_name',
        'project/partner/organization',
        'project/partner/orcid',
    }
    radar_import._attributes = {path: Attribute(path=path) for path in paths}
    option_paths = {
        'identifier_type/doi',
        'resource_type_general/dataset',
        'radar_data_source/observation',
    }
    radar_import._options = {path: Option(uri_path=path) for path in option_paths}
    radar_import.get_attribute = lambda uri: None
    radar_import.get_option = lambda uri: None
    return radar_import


def test_only_confirmed_dataset_paths_are_read():
    export = make_export()
    values = {
        'project/dataset/description': 'Canonical resource',
        'project/dataset/resource_type': 'Unconfirmed legacy resource',
        'project/dataset/title': 'Dataset title',
    }
    export.get_text = lambda path, **kwargs: values.get(path)
    export.get_option = lambda options, path, **kwargs: 'Dataset' if path == 'project/dataset/format' else None

    metadata = compute_metadata(export, 0)

    assert metadata.resource == Resource('Canonical resource', 'Dataset')
    assert metadata.title == 'Dataset title'


def test_creator_name_is_derived_from_structured_parts():
    export = make_export()
    export.get_set = lambda path, **kwargs: [SimpleNamespace(set_prefix='0', set_index=0)] \
        if path == 'project/dataset/creator/name' else []
    values = {
        'project/dataset/creator/given_name': 'Jane',
        'project/dataset/creator/family_name': 'Doe',
    }
    export.get_text = lambda path, **kwargs: values.get(path)

    metadata = compute_metadata(export, 0)

    assert metadata.creators[0].name == 'Doe, Jane'
    assert metadata.creators[0].given_name == 'Jane'
    assert metadata.creators[0].family_name == 'Doe'


def test_xml_and_api_adapters_share_canonical_model_but_not_wire_values():
    metadata = RadarMetadata(
        identifier=Identifier('10.1234/example', 'DOI'),
        creators=[Agent(
            name='Doe, Jane',
            name_type='Personal',
            affiliations=[Affiliation('First University'), Affiliation('Second University')],
        )],
        resource=Resource('Research data', 'Dataset'),
        rights=Rights('CC BY 4.0 Attribution'),
    )

    xml_data = to_xml_payload(metadata)
    api_data = to_api_payload(metadata)

    assert metadata.resource.resource_type == 'Dataset'
    assert xml_data['resource']['resourceType'] == 'Dataset'
    assert api_data['resource']['resourceType'] == 'DATASET'
    assert xml_data['creators']['creator'][0]['creatorAffiliation'] == 'First University'
    assert api_data['creators']['creator'][0]['creatorAffiliation'] == [
        'First University', 'Second University'
    ]


def test_xml_parser_preserves_canonical_rddm_values():
    xml = RadarExportRenderer().render({
        'identifier': '10.1234/example',
        'identifierType': 'DOI',
        'creators': {'creator': [{'creatorName': 'Doe, Jane'}]},
        'title': 'Dataset',
        'publishers': {'publisher': ['Repository']},
        'productionYear': '2026',
        'subjectAreas': {'subjectArea': [{'controlledSubjectAreaName': 'Chemistry'}]},
        'resource': {'value': 'Research data', 'resourceType': 'Dataset'},
        'rights': {'controlledRights': 'CC BY 4.0 Attribution'},
        'rightsHolders': {'rightsHolder': ['University']},
        'version': '2.1',
    })

    metadata = parse_xml(ElementTree.fromstring(xml))

    assert metadata.identifier == Identifier('10.1234/example', 'DOI')
    assert metadata.creators[0].name == 'Doe, Jane'
    assert metadata.publishers[0].name == 'Repository'
    assert metadata.resource == Resource('Research data', 'Dataset')
    assert metadata.version == '2.1'


def test_semantic_metadata_serializes_to_valid_rddm_9_3_xml():
    metadata = RadarMetadata(
        identifier=Identifier('10.1234/example', 'DOI'),
        creators=[Agent(
            name='Doe, Jane',
            affiliations=[Affiliation('Example University', 'https://ror.org/example', 'ROR')],
        )],
        title='Dataset',
        additional_titles=['DATA'],
        descriptions=[Description('Description')],
        publishers=[Agent('Example Repository')],
        production_year='2026',
        subject_areas=[SubjectArea('Chemistry')],
        resource=Resource('Research data', 'Dataset'),
        geo_locations=[GeoLocation(region='Berlin')],
        rights=Rights('CC BY 4.0 Attribution'),
        rights_holders=[Agent('Example University')],
    )

    payload = to_xml_payload(metadata)
    xml = RadarExportRenderer().render(payload)

    assert missing_required_fields(payload) == []
    assert validate_radar_xml(xml) is None


def test_import_uses_paths_and_option_uri_paths_not_host_specific_uris():
    radar_import = make_import('''
        <radar:radarDataset
            xmlns:radar="http://radar-service.eu/schemas/descriptive/radar/v09/radar-dataset"
            xmlns:re="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <re:identifier identifierType="DOI">10.1234/example</re:identifier>
          <re:title>Dataset title</re:title>
          <re:descriptions><re:description descriptionType="Abstract">Description</re:description></re:descriptions>
          <re:keywords><re:keyword>FAIR</re:keyword></re:keywords>
          <re:resource resourceType="Dataset">Research data</re:resource>
          <re:dataSources><re:dataSource dataSourceDetail="Observation">Survey data</re:dataSource></re:dataSources>
          <re:fundingReferences><re:fundingReference>
            <re:funderName>Example Funder</re:funderName>
            <re:awardNumber>ABC-123</re:awardNumber>
          </re:fundingReference></re:fundingReferences>
          <re:version>2.1</re:version>
        </radar:radarDataset>
    ''')

    radar_import.process()

    paths = {value.attribute.path for value in radar_import.values}
    option_paths = {value.option.uri_path for value in radar_import.values if value.option}
    assert 'project/dataset/data_publication_pid' in paths
    assert 'project/dataset/description' in paths
    assert 'project/dataset/format' in paths
    assert 'project/dataset/creation_methods' in paths
    assert 'project/funder/grant_nr' in paths
    assert 'resource_type_general/dataset' in option_paths
    assert 'project/dataset/version' not in paths
    assert {issue.field for issue in radar_import.mapping_issues} >= {'descriptions', 'version'}


def test_project_level_imports_are_deduplicated_across_datasets():
    radar_import = make_import('''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <title>Dataset title</title>
          <keywords><keyword>FAIR</keyword></keywords>
          <contributors><contributor contributorType="Other">
            <contributorName>Doe, Jane</contributorName>
            <givenName>Jane</givenName><familyName>Doe</familyName>
            <nameIdentifier nameIdentifierScheme="ORCID">0000-0001</nameIdentifier>
          </contributor></contributors>
          <fundingReferences><fundingReference>
            <funderName>Example Funder</funderName><awardNumber>ABC-123</awardNumber>
          </fundingReference></fundingReferences>
        </radarDataset>
    ''')

    radar_import.process()
    radar_import.process()

    global_values = [value for value in radar_import.values if value.attribute.path in {
        'project/research_question/keywords', 'project/partner/name', 'project/funder/name'
    }]
    assert [(value.attribute.path, value.text) for value in global_values] == [
        ('project/research_question/keywords', 'FAIR'),
        ('project/partner/name', 'Doe, Jane'),
        ('project/funder/name', 'Example Funder'),
    ]


def test_api_vocabulary_is_derived_from_xml_vocabulary():
    metadata = RadarMetadata(
        related_identifiers=[Identifier('id', 'RAiD', 'IsTranslationOf')],
    )

    api = to_api_payload(metadata)

    assert XMLVocabulary.related_identifier_type_options['identifier_type/raid'] == 'RAiD'
    assert api['relatedIdentifiers']['relatedIdentifier'][0] == {
        'value': 'id',
        'relatedIdentifierType': 'RAID',
        'relationType': 'IS_TRANSLATION_OF',
    }
