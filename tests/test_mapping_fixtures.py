import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from django.template import Context, Engine, RequestContext
from django.test import RequestFactory, override_settings
from django.utils.translation import override

from rdmo.core.xml import parse_xml_to_elements
from rdmo.domain.models import Attribute
from rdmo.management.imports import import_elements
from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot, Value
from rdmo.questions.models import Catalog, QuestionSet

from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExport, RadarExportProvider
from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import get_radar_schema, get_radar_validation_errors
from rdmo_radar.metadata.crosswalks import SUBJECT_OPTIONS
from rdmo_radar.metadata.rdmo import RDMOReadContext
from rdmo_radar.metadata.types import Agent, FundingReference, Identifier, RadarMetadata, Resource, Rights, SubjectArea
from rdmo_radar.metadata.validation import missing_required_fields
from rdmo_radar.metadata.xml import parse_xml, to_xml_payload

XML_DIRECTORY = Path(__file__).parent / 'xml'
URI = '{http://purl.org/dc/elements/1.1/}uri'


@pytest.fixture(scope='session')
def imported_catalog(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        elements, errors = parse_xml_to_elements(XML_DIRECTORY / 'dmp4nfdi_v2-0-0.xml')
        assert not errors
        imported = import_elements(elements)
        assert not [(element['uri'], element['errors']) for element in imported if element.get('errors')]
        return Catalog.objects.get(uri_path='dmp4nfdi/v2-0-0').pk


@pytest.fixture
def prototype(imported_catalog, db):
    root = ElementTree.parse(XML_DIRECTORY / 'RADAR Plugin Testprojekt.xml').getroot()
    project = Project.objects.create(title=root.findtext('title'), catalog_id=imported_catalog)
    attributes = {attribute.uri: attribute for attribute in Attribute.objects.all()}
    options = {option.uri: option for option in Option.objects.all()}
    Value.objects.bulk_create([
        Value(
            project=project,
            attribute=attributes[node.find('attribute').get(URI)],
            option=options.get(node.find('option').get(URI)),
            text=node.findtext('text') or '',
            external_id=node.findtext('external_id') or '',
            value_type=node.findtext('value_type'),
            created=node.findtext('created'),
            updated=node.findtext('updated'),
            set_prefix=node.findtext('set_prefix') or '',
            set_index=int(node.findtext('set_index')),
            collection_index=int(node.findtext('collection_index')),
        ) for node in root.findall('./values/value')
    ])
    return project


def export_for(project, cls=RadarExport):
    export = cls('radar', 'RADAR', f'rdmo_radar.exports.{cls.__name__}')
    export.project = project
    export.request = SimpleNamespace(session={}, user=SimpleNamespace(email='user@example.test'), LANGUAGE_CODE='en')
    return export


def add_value(project, path, text='', option=None, **kwargs):
    attribute = Attribute.objects.filter(path=path).first()
    if attribute is None:
        parent_path, _, key = path.rpartition('/')
        parent = Attribute.objects.filter(path=parent_path).first()
        attribute = Attribute.objects.create(key=key, parent=parent, uri_prefix='https://example.test/terms')
        # Isolated optional attributes need not require the entire domain tree.
        Attribute.objects.filter(pk=attribute.pk).update(path=path)
        attribute.path = path
    return Value.objects.create(project=project, attribute=attribute, text=text, option=option, **kwargs)


@pytest.fixture
def observed_draft_project(prototype):
    # The live RDMO answers gained Web scraping after the saved prototype snapshot.
    add_value(prototype, 'project/dataset/creation_methods',
              option=Option.objects.get(uri_path='dfg_new_data/dfg-nd_11'),
              set_prefix='0', set_index=0, collection_index=11, value_type='option')
    return prototype


@pytest.fixture
def observed_draft_metadata():
    # Explicit expectations from the downloaded document, independent of both adapters.
    return RadarMetadata(
        title='Radar Testdatensatz Nr 1',
        additional_titles=['RADAR Test'],
        keywords=['Schlagwort 1', 'Schlagwort 2', 'Schlagwort 3'],
        subject_areas=[SubjectArea('Other', 'Humanities and Social Sciences / Ancient Cultures')],
        resource=Resource('ein Datensatz zum testen des neuen RADAR Plugins'),
        data_sources=[
            Resource('Surveys', 'Survey'),
            Resource('Laboratory experiments', 'Trial'),
            Resource('Social science experiments', 'Trial'),
            Resource('Web scraping', 'Other'),
        ],
        rights=Rights('CC BY 4.0 Attribution'),
        funding_references=[FundingReference(funder_name='DFG', award_number='123345', award_title='Program42')],
    )


def xml_structure(element):
    """Compare expanded names and all values, ignoring indentation and prefix spelling."""
    return (
        element.tag, element.attrib,
        element.text if element.text and element.text.strip() else '',
        element.tail if element.tail and element.tail.strip() else '',
        tuple(xml_structure(child) for child in element),
    )


def test_downloaded_radar_draft_parses_expected_metadata(observed_draft_metadata):
    path = XML_DIRECTORY / 'RADAR_DATASET_DESCRIPTIVE_METADATA.xml'
    metadata = parse_xml(ElementTree.parse(path).getroot())
    assert metadata == observed_draft_metadata
    assert missing_required_fields(metadata) == (
        'identifier', 'identifier.identifierType', 'creators.creator', 'publishers.publisher',
        'productionYear', 'resource.resourceType', 'rightsHolders.rightsHolder',
    )
    # RADAR accepted a draft, not a document complete enough for the bundled XSD.
    assert get_radar_validation_errors(path)


def test_updated_prototype_xml_matches_downloaded_radar_draft(observed_draft_project, observed_draft_metadata):
    export = export_for(observed_draft_project)
    assert export.compute_metadata(0) == observed_draft_metadata
    assert export.compute_metadata(1).data_sources == []
    first = export.prepare_files()[0]
    expected = ElementTree.parse(XML_DIRECTORY / 'RADAR_DATASET_DESCRIPTIVE_METADATA.xml').getroot()
    assert xml_structure(ElementTree.fromstring(first.xml_data)) == xml_structure(expected)
    assert tuple(field.path for field in first.missing_fields) == missing_required_fields(observed_draft_metadata)
    assert first.has_warnings and first.validation_errors and not first.mapping_issues

    export.request = RequestFactory().get('/', {'download': '1'})
    with zipfile.ZipFile(io.BytesIO(export.render().content)) as archive:
        assert archive.read(first.file_name) == first.xml_data


@pytest.mark.parametrize('cls', [RadarExportProvider, RadarCredentialsExportProvider])
def test_both_providers_export_observed_radar_draft(observed_draft_project, cls):
    provider = export_for(observed_draft_project, cls)
    # Hand-written REST expectation: do not derive wire shapes from the XML fixture/parser.
    assert provider.get_post_data('0')['descriptiveMetadata'] == {
        'title': 'Radar Testdatensatz Nr 1',
        'additionalTitles': {'additionalTitle': [{'value': 'RADAR Test', 'additionalTitleType': 'OTHER'}]},
        'keywords': {'keyword': [
            {'value': 'Schlagwort 1'}, {'value': 'Schlagwort 2'}, {'value': 'Schlagwort 3'},
        ]},
        'subjectAreas': {'subjectArea': [{
            'controlledSubjectAreaName': 'OTHER',
            'additionalSubjectAreaName': 'Humanities and Social Sciences / Ancient Cultures',
        }]},
        'resource': {'value': 'ein Datensatz zum testen des neuen RADAR Plugins'},
        'dataSources': {'dataSource': [
            {'value': 'Surveys', 'dataSourceDetail': 'SURVEY'},
            {'value': 'Laboratory experiments', 'dataSourceDetail': 'TRIAL'},
            {'value': 'Social science experiments', 'dataSourceDetail': 'TRIAL'},
            {'value': 'Web scraping', 'dataSourceDetail': 'OTHER'},
        ]},
        'rights': {'controlledRights': 'CC_BY_4_0_ATTRIBUTION'},
        'fundingReferences': {'fundingReference': [{
            'funderName': 'DFG', 'awardNumber': '123345', 'awardTitle': 'Program42',
        }]},
    }
    assert 'dataSources' not in provider.get_post_data('1')['descriptiveMetadata']


def test_prototype_metadata_preserves_answers_and_dataset_boundaries(prototype):
    export = export_for(prototype)
    assert export.get_dataset_indices() == [0, 1]
    first = export.compute_metadata(0)
    second = export.compute_metadata(1)
    assert first.title == 'Radar Testdatensatz Nr 1'
    assert second.title == 'Radar Testdatensatz Nr 2'
    assert first.resource == Resource('ein Datensatz zum testen des neuen RADAR Plugins', None)
    assert [source.resource_type for source in first.data_sources] == ['Survey', 'Trial', 'Trial']
    assert [source.value for source in first.data_sources] == [
        'Surveys', 'Laboratory experiments', 'Social science experiments',
    ]
    assert first.rights == Rights('CC BY 4.0 Attribution')
    assert second.resource is None
    assert second.data_sources == []
    assert second.rights is None
    for metadata in (first, second):
        assert metadata.keywords == ['Schlagwort 1', 'Schlagwort 2', 'Schlagwort 3']
        assert metadata.additional_titles == ['RADAR Test']
        assert metadata.subject_areas == [SubjectArea('Other', 'Humanities and Social Sciences / Ancient Cultures')]
        assert len(metadata.funding_references) == 1
        funding = metadata.funding_references[0]
        assert (funding.funder_name, funding.award_number, funding.award_title) == ('DFG', '123345', 'Program42')
        assert funding.funder_identifier is None
        assert metadata.production_year is None
        assert metadata.processing == []
        assert metadata.creators == metadata.contributors == []


def test_file_formats_never_become_resource_types_or_mapping_issues(prototype):
    export = export_for(prototype)
    metadata = export.compute_metadata(0)
    assert metadata.resource.resource_type is None
    assert not any(issue.source == 'project/dataset/format' for issue in metadata.mapping_issues)
    assert 'resource.resourceType' not in {issue.field for issue in metadata.mapping_issues}


@pytest.mark.parametrize('cls', [RadarExportProvider, RadarCredentialsExportProvider])
def test_both_providers_offer_collection_labels_and_shared_metadata(prototype, cls):
    provider = export_for(prototype, cls)
    provider.prepare_export_session()
    assert provider.get_from_session(provider.request, 'dataset_choices') == [
        (0, 'Radar Testdatensatz Nr 1'), (1, 'Radar Testdatensatz Nr 2'),
    ]
    form = provider.get_export_form(workspace_choices=[('workspace', 'Workspace')])
    assert len(form.mapping_warnings) == 2
    assert 'Resource type' in form.mapping_warnings[0]['missing']
    assert not form.mapping_warnings[0]['issues']
    payload = provider.get_post_data('0')['descriptiveMetadata']
    assert payload['title'] == 'Radar Testdatensatz Nr 1'
    assert [source['dataSourceDetail'] for source in payload['dataSources']['dataSource']] == [
        'SURVEY', 'TRIAL', 'TRIAL',
    ]
    assert payload['rights']['controlledRights'] == 'CC_BY_4_0_ATTRIBUTION'
    assert payload['fundingReferences']['fundingReference'][0]['awardNumber'] == '123345'
    assert 'mapping_issues' not in payload
    assert 'resource' not in provider.get_dataset('1')


def test_prototype_xml_reports_gaps_and_downloads_both_files(prototype):
    export = export_for(prototype)
    files = export.prepare_files()
    assert [file.file_name for file in files] == ['Radar Testdatensatz Nr 1.xml', 'Radar Testdatensatz Nr 2.xml']
    first = files[0]
    assert first.has_warnings and not first.mapping_issues
    assert {'identifier', 'creators.creator', 'productionYear', 'resource.resourceType'} <= {
        field.path for field in first.missing_fields
    }
    assert b'Surveys' in first.xml_data
    assert b'123345' in first.xml_data
    assert b'Ancient Cultures' in first.xml_data
    assert b'mapping_issues' not in first.xml_data
    export.request = RequestFactory().get('/', {'download': '1'})
    response = export.render()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 2


def test_explicit_title_precedes_collection_label_and_zip_names_are_safe(prototype):
    add_value(prototype, 'project/dataset/title', '../same/name', set_index=0)
    add_value(prototype, 'project/dataset/title', '../same/name', set_index=1)
    export = export_for(prototype)
    assert export.compute_metadata(0).title == '../same/name'
    assert export.get_dataset_indices() == [0, 1]
    files = export.prepare_files()
    assert len({file.file_name for file in files}) == 2
    assert all('/' not in file.file_name and '\\' not in file.file_name for file in files)


def test_nested_prefixes_do_not_mix_dataset_one_and_ten(prototype):
    add_value(prototype, 'project/dataset/id', 'Dataset ten', set_index=10)
    add_value(prototype, 'project/dataset/description', 'Second dataset', set_prefix='1')
    add_value(prototype, 'project/dataset/description', 'Tenth dataset', set_prefix='10')
    export = export_for(prototype)
    assert export.get_dataset_indices() == [0, 1, 10]
    assert export.compute_metadata(1).resource.value == 'Second dataset'
    assert export.compute_metadata(10).resource.value == 'Tenth dataset'


def test_snapshot_selection_invalidates_answer_cache(prototype):
    snapshot = Snapshot.objects.create(project=prototype, title='Earlier answers')
    prototype.values.filter(snapshot=None, attribute__path='project/dataset/description').update(text='Current answer')
    export = export_for(prototype)
    assert export.compute_metadata(0).resource.value == 'Current answer'
    export.snapshot = snapshot
    assert export.compute_metadata(0).resource.value == 'ein Datensatz zum testen des neuen RADAR Plugins'
    export.snapshot = None
    assert export.compute_metadata(0).resource.value == 'Current answer'


def test_all_catalog_subjects_have_schema_valid_crosswalks(prototype):
    options = Option.objects.filter(uri_path__startswith='research_fields/')
    assert set(options.values_list('uri_path', flat=True)) == set(SUBJECT_OPTIONS)
    value = prototype.values.get(attribute__path='project/research_field/title')
    for option in options:
        value.option = option
        value.save()
        subjects = export_for(prototype).compute_metadata(0).subject_areas
        assert subjects
        assert all(subject.additional_name for subject in subjects if subject.controlled_name == 'Other')
        assert all(get_radar_schema().maps.types[
            '{http://radar-service.eu/schemas/descriptive/radar/v09/radar-types}subjectArea'
        ].is_valid(subject.controlled_name) for subject in subjects)
    value.option = options.get(uri_path='research_fields/182')
    value.save()
    assert [subject.controlled_name for subject in export_for(prototype).compute_metadata(0).subject_areas] == [
        'Biology', 'Life Science', 'Medicine',
    ]
    value.option = options.get(uri_path='research_fields/211')
    value.save()
    metadata = export_for(prototype).compute_metadata(0)
    assert metadata.subject_areas[0].controlled_name == 'Other'
    assert any('uncertain' in issue.reason for issue in metadata.mapping_issues)


def test_creation_methods_cover_every_catalog_option_and_preserve_free_text(prototype):
    prototype.values.filter(attribute__path='project/dataset/creation_methods').delete()
    options = list(Option.objects.filter(uri_path__startswith='dfg_new_data/').order_by('uri_path'))
    assert len(options) == 15
    for index, option in enumerate(options):
        add_value(prototype, 'project/dataset/creation_methods', 'Custom method' if index == 14 else '',
                  option=option, set_prefix='0', collection_index=index + 3)
    metadata = export_for(prototype).compute_metadata(0)
    assert [source.resource_type for source in metadata.data_sources] == [
        'Observation', 'Survey', 'Survey', 'Trial', 'Trial', 'Trial', *(['Other'] * 9),
    ]
    assert metadata.data_sources[-1].value == 'Other: Custom method'
    with override('de'):
        german = export_for(prototype).compute_metadata(0)
    assert [source.resource_type for source in german.data_sources] == [
        source.resource_type for source in metadata.data_sources
    ]
    assert german.data_sources[0].value != metadata.data_sources[0].value


def test_all_licenses_and_conflicts(prototype):
    value = prototype.values.get(attribute__path='project/dataset/sharing/conditions')
    expected = {
        '71': 'CC BY 4.0 Attribution', '73': 'CC BY-NC 4.0 Attribution-NonCommercial',
        '74': 'CC BY-ND 4.0 Attribution-NoDerivs', '75': 'CC BY-SA 4.0 Attribution-ShareAlike',
        'cc0': 'CC0 1.0 Universal Public Domain Dedication', '233': 'Other',
        'ODC-By': 'Attribution License (ODC-By)', 'ODbl': 'Open Database License (ODC-ODbL)',
    }
    for suffix, controlled in expected.items():
        value.option = Option.objects.get(uri_path=f'dataset_license_types/{suffix}')
        value.text = 'Custom terms' if suffix == '233' else ''
        value.save()
        rights = export_for(prototype).compute_metadata(0).rights
        assert rights.controlled == controlled
        if suffix == '233':
            assert 'Custom terms' in rights.additional
    add_value(prototype, 'project/dataset/sharing/conditions', collection_index=5,
              option=Option.objects.get(uri_path='dataset_license_types/71'))
    metadata = export_for(prototype).compute_metadata(0)
    assert metadata.rights is None
    assert any(issue.field == 'rights' for issue in metadata.mapping_issues)


def test_funders_without_markers_preserve_multiple_group_boundaries(prototype):
    questionset = QuestionSet.objects.get(questions__attribute__path='project/funder/name')
    questionset.is_collection = True
    questionset.save()
    add_value(prototype, 'project/funder/name', 'Second funder', set_prefix='0', set_index=2)
    add_value(prototype, 'project/funder/grant_nr', 'SECOND', set_prefix='0', set_index=2)
    funders = export_for(prototype).compute_metadata(0).funding_references
    assert [(funder.funder_name, funder.award_number) for funder in funders] == [
        ('DFG', '123345'), ('Second funder', 'SECOND'),
    ]


def test_software_exports_only_explicit_details_and_warns_about_version(prototype):
    # This catalog asks the question directly on a non-collection project-level page.
    option = Option.objects.get(uri_path='dmp4nfdi/v2-0-0/ur00')
    add_value(prototype, 'project/dataset/usage_technology', 'Example Viewer', option=option)
    metadata = export_for(prototype).compute_metadata(0)
    assert [(software.name, software.software_type, software.version) for software in metadata.software] == [
        ('Example Viewer', 'Resource Viewing', None),
    ]
    assert any(issue.field == 'software.softwareVersion' for issue in metadata.mapping_issues)
    xml = RadarExportRenderer().render(to_xml_payload(metadata))
    assert 'Example Viewer' in xml
    assert any('softwareVersion' in error for error in get_radar_validation_errors(xml))


def test_complete_mapped_metadata_validates_against_rddm(prototype):
    metadata = export_for(prototype).compute_metadata(0)
    # Supply the fields deliberately absent from the interview prototype.
    metadata.identifier = Identifier('10.1234/example', 'DOI')
    metadata.creators = [Agent('Example creator')]
    metadata.publishers = [Agent('Example publisher')]
    metadata.production_year = '2026'
    metadata.resource.resource_type = 'Dataset'
    metadata.rights_holders = [Agent('Example rights holder')]
    xml = RadarExportRenderer().render(to_xml_payload(metadata))
    assert get_radar_validation_errors(xml) == ()


def test_partner_groups_use_names_and_external_identifiers_not_role_labels(prototype):
    role = Option.objects.get(uri_path='crt00')
    for index, given, family, orcid in (
        (0, 'Jane', 'Doe', '0000-0001-2345-6789'),
        (3, 'John', 'Smith', '0000-0002-2345-6789'),
    ):
        group = {'set_prefix': '0|0', 'set_index': index}
        add_value(prototype, 'project/partner/name', option=role, collection_index=5, **group)
        add_value(prototype, 'project/partner/given_name', given, **group)
        add_value(prototype, 'project/partner/family_name', family, **group)
        add_value(prototype, 'project/partner/orcid', f'<a href="https://orcid.org/{orcid}">ORCID</a>',
                  external_id=orcid, **group)
    # A role-only group must not create a fictitious person named "Data management".
    add_value(prototype, 'project/partner/name', option=role, set_prefix='0|0', set_index=7)
    metadata = export_for(prototype).compute_metadata(0)
    assert [agent.name for agent in metadata.contributors] == ['Doe, Jane', 'Smith, John']
    assert [agent.identifiers[0].value for agent in metadata.contributors] == [
        '0000-0001-2345-6789', '0000-0002-2345-6789',
    ]
    assert all(agent.contributor_type == 'Other' for agent in metadata.contributors)
    assert '&lt;a ' not in RadarExportRenderer().render(to_xml_payload(metadata))


def test_ambiguous_scalar_and_markup_identifier_produce_mapping_issues(prototype):
    add_value(prototype, 'project/dataset/description', 'Conflicting description',
              set_prefix='0', collection_index=8)
    metadata = export_for(prototype).compute_metadata(0)
    assert metadata.resource is None
    issue = next(issue for issue in metadata.mapping_issues if issue.field == 'resource')
    assert issue.source == 'project/dataset/description'
    add_value(prototype, 'project/partner/given_name', 'Jane', set_prefix='0|0')
    add_value(prototype, 'project/partner/orcid', '<a href="https://orcid.org/example">Jane</a>', set_prefix='0|0')
    metadata = export_for(prototype).compute_metadata(0)
    assert metadata.contributors[0].identifiers == []
    assert any(issue.field == 'nameIdentifier' for issue in metadata.mapping_issues)


def test_unknown_vocabulary_entries_preserve_labels(prototype):
    option = Option.objects.create(uri_prefix='https://example.test/terms', uri_path='new-option',
                                   text_lang1='Unlisted choice')
    value = prototype.values.get(attribute__path='project/research_field/title')
    value.option = option
    value.text = 'Details'
    value.save()
    prototype.values.filter(attribute__path='project/dataset/creation_methods').delete()
    add_value(prototype, 'project/dataset/creation_methods', 'Source details', option=option, set_prefix='0')
    metadata = export_for(prototype).compute_metadata(0)
    assert metadata.subject_areas == [SubjectArea('Other', 'Unlisted choice: Details')]
    assert metadata.data_sources == [Resource('Unlisted choice: Source details', 'Other')]
    assert {'subjectAreas', 'dataSources'} <= {issue.field for issue in metadata.mapping_issues}


def test_legacy_flat_layout_and_nested_creators_without_catalog(db):
    project = Project.objects.create(title='Legacy project')
    add_value(project, 'project/dataset/id', 'Legacy dataset', set_index=2)
    add_value(project, 'project/dataset/description', 'Legacy description', set_index=2)
    add_value(project, 'project/dataset/creator/given_name', 'Jane', set_prefix='2')
    add_value(project, 'project/dataset/creator/family_name', 'Doe', set_prefix='2')
    add_value(project, 'project/dataset/creator/given_name', 'Unrelated', set_prefix='20')
    add_value(project, 'project/funder/name', 'Funder without ID', set_index=4)
    export = export_for(project)
    assert export.get_dataset_indices() == [2]
    metadata = export.compute_metadata(2)
    assert metadata.title == 'Legacy dataset'
    assert metadata.resource.value == 'Legacy description'
    assert [creator.name for creator in metadata.creators] == ['Doe, Jane']
    assert metadata.funding_references[0].funder_name == 'Funder without ID'


def test_answers_are_indexed_once_per_project_snapshot(prototype, django_assert_num_queries):
    export = export_for(prototype)
    export.compute_metadata(0)
    with django_assert_num_queries(0):
        export.compute_metadata(1)
        export.get_dataset_indices()
        export.get_dataset_title(0)


def test_import_resolves_installed_uri_aliases_through_public_api(prototype):
    from rdmo_radar.imports import RadarImport
    from rdmo_radar.metadata.rdmo import RDMOWriteContext

    attribute = Attribute.objects.get(path='project/dataset/description')
    attribute.uri_prefix = 'https://custom.example.test/terms'
    attribute.save()
    option = Option.objects.get(uri_path='radar_data_source/survey') if Option.objects.filter(
        uri_path='radar_data_source/survey').exists() else Option.objects.create(
            uri_prefix='https://custom.example.test/terms', uri_path='radar_data_source/survey', text_lang1='Survey')
    option.uri_prefix = 'https://custom.example.test/terms'
    option.save()
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')
    plugin.current_project = prototype
    context = RDMOWriteContext(plugin, 2)
    assert context.get_attribute('project/dataset/description') == attribute
    assert context.get_option('radar_data_source/survey') == option
    assert context.get_attribute('project/missing') is None
    assert context.get_option('missing') is None


@pytest.mark.parametrize(('language', 'url_language'), [('en', 'en'), ('de', 'de')])
def test_completed_export_records_id_and_url_for_selected_dataset(prototype, language, url_language):
    add_value(prototype, 'project/dataset/radar_id', 'existing-id', set_index=0)
    add_value(prototype, 'project/dataset/radar_url', 'existing-url', set_index=0)
    provider = export_for(prototype, RadarCredentialsExportProvider)
    provider.request.LANGUAGE_CODE = language
    provider.store_in_session(provider.request, 'project_id', prototype.pk)
    provider.store_in_session(provider.request, 'set_index', '1')
    response = provider.complete_export(provider.request, 'new-id')
    expected_url = f'https://radar.example.test/radar/{url_language}/dataset/new-id'
    assert response.url == expected_url
    assert prototype.values.get(attribute__path='project/dataset/radar_id', set_index=1).text == 'new-id'
    assert prototype.values.get(attribute__path='project/dataset/radar_url', set_index=1).text == expected_url
    assert prototype.values.get(attribute__path='project/dataset/radar_id', set_index=0).text == 'existing-id'


def test_software_negative_choices_and_empty_details_are_not_exported(prototype):
    for index in range(5):
        add_value(prototype, 'project/dataset/usage_technology', '' if index == 0 else 'Display text',
                  option=Option.objects.get(uri_path=f'dmp4nfdi/v2-0-0/ur{index:02}'), collection_index=index)
    assert export_for(prototype).compute_metadata(0).software == []


def test_shared_software_and_distinct_project_values_do_not_leak(prototype):
    add_value(prototype, 'project/dataset/usage_technology', 'Shared Viewer',
              option=Option.objects.get(uri_path='dmp4nfdi/v2-0-0/ur00'))
    export = export_for(prototype)
    assert export.compute_metadata(1).software[0].name == 'Shared Viewer'
    second_project = Project.objects.create(title='Other project', catalog=prototype.catalog)
    add_value(second_project, 'project/dataset/id', 'Other dataset')
    export.project = second_project
    assert export.compute_metadata(0).software == []
    assert export.compute_metadata(0).keywords == []


def test_software_stays_in_both_adapters_without_a_version(prototype):
    add_value(prototype, 'project/dataset/usage_technology', 'Shared Viewer',
              option=Option.objects.get(uri_path='dmp4nfdi/v2-0-0/ur00'))
    xml = export_for(prototype).get_dataset(0)
    api = export_for(prototype, RadarExportProvider).get_dataset(0)
    assert xml['software'][0]['type'] == 'Resource Viewing'
    assert api['software']['softwareType'][0]['type'] == 'RESOURCE_VIEWING'
    assert xml['software'][0]['softwareName'] == 'Shared Viewer'
    assert api['software']['softwareType'][0]['softwareName'] == [{'value': 'Shared Viewer'}]


def test_sparse_keyword_indices_and_duplicate_text(prototype):
    add_value(prototype, 'project/research_question/keywords', 'Schlagwort 1', collection_index=8)
    add_value(prototype, 'project/research_question/keywords', 'Fourth keyword', collection_index=15)
    add_value(prototype, 'project/research_question/keywords', '   ', collection_index=16)
    context = RDMOReadContext(export_for(prototype)).shared()
    assert context.get_texts('project/research_question/keywords') == [
        'Schlagwort 1', 'Schlagwort 2', 'Schlagwort 3', 'Fourth keyword',
    ]


@override_settings(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'APP_DIRS': True,
    'OPTIONS': {'libraries': {'widget_tweaks': 'widget_tweaks.templatetags.widget_tweaks'}},
}])
def test_mapping_warnings_render_and_escape_answer_text(prototype):
    option = Option.objects.create(uri_prefix='https://example.test/terms', uri_path='unknown-method',
                                   text_lang1='Unknown method')
    add_value(prototype, 'project/dataset/creation_methods', '<script>alert(1)</script>',
              option=option, set_prefix='0', collection_index=9)
    template_directory = Path(__file__).parents[1] / 'rdmo_radar' / 'templates'
    engine = Engine(
        dirs=[str(template_directory)],
        libraries={'i18n': 'django.templatetags.i18n', 'core_tags': 'rdmo.core.templatetags.core_tags'},
        loaders=[
            ('django.template.loaders.locmem.Loader', {'core/page.html': '{% block page %}{% endblock %}'}),
            'django.template.loaders.filesystem.Loader',
        ],
    )
    export = export_for(prototype)
    html = engine.get_template('plugins/exports_radar_xml_validation.html').render(Context({
        'files': export.prepare_files(), 'project_url': '/projects/1/',
    }))
    assert 'Mapping warnings' in html
    assert 'Download anyway' in html
    assert '&lt;script&gt;' in html
    assert '<script>' not in html
    provider = export_for(prototype, RadarCredentialsExportProvider)
    provider.prepare_export_session()
    form = provider.get_export_form(workspace_choices=[('workspace', 'Workspace')])
    request = RequestFactory().get('/')
    html = engine.get_template('plugins/exports_radar.html').render(RequestContext(request, {'form': form}))
    assert 'You can export them as drafts' in html
    assert 'Radar Testdatensatz Nr 2' in html
    assert '&lt;script&gt;' in html
    assert '<script>' not in html
