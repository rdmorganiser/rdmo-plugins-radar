"""Provenance follows real mapping decisions and the emitted XML/REST values."""
import json
from dataclasses import fields, is_dataclass, replace
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from django.template.loader import render_to_string

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot, Value

from rdmo_radar.exports import (
    RadarProjectCredentialsExportProvider,
    RadarProjectExportProvider,
)
from rdmo_radar.exports import (
    RadarTemplateFrameworkCredentialsExportProvider as RadarCredentialsExportProvider,
)
from rdmo_radar.exports import (
    RadarTemplateFrameworkExportProvider as RadarExportProvider,
)
from rdmo_radar.exports.exports import RadarTemplateFrameworkExport as RadarExport
from rdmo_radar.exports.previews import compute_mapping_preview, compute_payload_field_path, compute_source_answers
from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.mappings import ExportDataset
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING
from rdmo_radar.mappings.template_framework.vocabulary import XMLVocabulary
from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.provenance import json_leaves, rebase_mapping, validate_payload_provenance, xml_leaves
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.types import (
    Affiliation,
    Description,
    FundingReference,
    GeoLocation,
    Identifier,
    MappingAttempt,
    MappingIssue,
    MappingResult,
    MappingSource,
    PersonOrOrganization,
    RadarMetadata,
    Resource,
    Software,
)
from rdmo_radar.metadata.xml import to_xml_payload

from .helpers import (
    add_answer,
    add_data_management_role,
    add_namespaced_attribute,
    complete_metadata,
    export_for,
    make_data_management_mapping,
    make_data_management_project,
)
from .test_exports import export_provider
from .test_typed_metadata import attach_catalog
from .test_value_scopes import add_page, add_question, add_questionset


def test_context_records_actual_normalization_ambiguity_and_missing_answers():
    attribute = Attribute(path='research/title')
    values = [Value(attribute=attribute, text=text, collection_index=index)
              for index, text in enumerate((' Title ', 'Title'))]
    context = ProjectReadContext({'research/title': values}, {}, provenance=[])
    assert context.get_text('research/title', target='title') == 'Title'
    assert [(row.outcome, row.value) for row in context.provenance] == [('skipped', None), ('mapped', 'Title')]
    assert context.provenance[0].sources[0].value is values[1]
    assert context.provenance[1].sources[0].value is values[0]
    assert all(value.pk is None for value in values)
    context.shared().get_text('missing', target='resource.value')
    assert context.provenance[-1].outcome == 'empty'
    assert context.group('', 0).provenance is context.provenance
    values.append(Value(attribute=attribute, text='Different'))
    context = ProjectReadContext({'research/title': values}, {}, provenance=[])
    assert context.get_text('research/title', target='title') is None
    assert context.provenance[-1].outcome == 'rejected'
    assert not any(row.outcome == 'mapped' for row in context.provenance)


@pytest.fixture
def traced_project(db):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'First dataset', set_index=1)
    add_answer(project, 'project/dataset/title', 'Tenth dataset', set_index=10)
    add_answer(project, 'project/dataset/description', 'Description', set_index=1)
    path = next(path for path, value in XMLVocabulary.language_options.items() if value == 'eng')
    option = Option.objects.create(uri_prefix='https://example.test/terms', uri_path=path, text_lang1='English')
    language = add_answer(project, 'project/dataset/language', '', set_index=1)
    language.option = option
    language.save()
    add_answer(project, 'project/dataset/creator/given_name', 'Jane', set_prefix='1', set_index=2)
    add_answer(project, 'project/dataset/creator/family_name', 'Doe', set_prefix='1', set_index=2)
    add_answer(project, 'project/dataset/creator/affiliation', 'University', set_prefix='1', set_index=2)
    add_answer(project, 'project/dataset/creator/name', 'Other creator', set_prefix='10')
    add_answer(project, 'project/funder/name', 'Shared funder', set_index=7)
    add_answer(project, 'project/funder/grant_nr', 'GRANT-7', set_index=7)
    add_answer(project, 'project/research_question/keywords', 'Shared keyword')
    add_answer(project, 'project/research_question/keywords', ' Shared keyword ', collection_index=1)
    return project


@pytest.mark.parametrize('kind', ['xml', 'api'])
def test_trace_matches_output_without_extra_value_queries_or_different_metadata(
    traced_project, kind, django_assert_num_queries,
):
    factory = build_xml_export_service if kind == 'xml' else build_export_service
    normal = factory(
        traced_project, profile=TEMPLATE_FRAMEWORK_MAPPING, **({'clock': lambda: 100} if kind == 'api' else {})
    )
    traced = factory(
        traced_project,
        profile=TEMPLATE_FRAMEWORK_MAPPING,
        collect_mapping=True,
        **({'clock': lambda: 100} if kind == 'api' else {}),
    )
    dataset = ExportDataset('1', 'Dataset', {'set_prefix': '', 'set_index': 1})
    with django_assert_num_queries(0):
        if kind == 'xml':
            plain = normal.compute_files([dataset])[0]
            result = traced.compute_files([dataset])[0]
            assert plain.xml_data == result.xml_data
            output = xml_leaves(result.xml_data)
        else:
            plain = normal.compute_payload(dataset, 'user@example.test')
            result = traced.compute_payload(dataset, 'user@example.test')
            assert plain.payload == result.payload
            output = dict(json_leaves(result.payload))
    assert plain.provenance is None
    rows = result.provenance
    assert rows is not None
    for row in rows:
        if not row.unsuccessful:
            assert output[row.output_path] == row.output_value
    language = next(row for row in rows if row.field == 'language' and row.output_path)
    assert language.value == 'eng'
    assert language.sources[0].value.option.uri.endswith('options/' + language.sources[0].value.option.uri_path)
    assert language.output_value == ('eng' if kind == 'xml' else 'ENG')
    creator = next(row for row in rows if row.field == 'creators[0].name' and row.output_path)
    assert creator.outcome == 'defaulted'
    assert creator.output_value == 'Doe, Jane'
    assert {source.value.text for source in creator.sources} == {'Jane', 'Doe'}
    assert {source.value.set_prefix for source in creator.sources} == {'1'}
    assert not any(getattr(source.value, 'text', '') == 'Other creator' for row in rows for source in row.sources)
    funder = next(row for row in rows if row.field == 'funding_references[0].funder_name' and row.output_path)
    assert funder.sources[0].value.text == 'Shared funder'
    assert funder.sources[0].value.set_index == 7
    assert any(row.outcome == 'skipped' and row.reason == 'Duplicate normalized text' for row in rows)
    assert any(row.outcome == 'empty' for row in rows)
    name_type = next(row for row in rows if row.field == 'creators[0].name_type' and row.outcome != 'empty')
    assert name_type.outcome == ('skipped' if kind == 'xml' else 'defaulted')


def test_snapshot_trace_references_only_snapshot_values(traced_project):
    snapshot = Snapshot.objects.create(project=traced_project, title='Saved')
    live = traced_project.values.get(attribute__path='project/dataset/title', snapshot=None, set_index=1)
    live.text = 'Changed live'
    live.save()
    service = build_xml_export_service(
        traced_project, profile=TEMPLATE_FRAMEWORK_MAPPING, snapshot=snapshot, collect_mapping=True
    )
    result = service.compute_files([ExportDataset('1', 'Dataset', {'set_prefix': '', 'set_index': 1})])[0]
    assert b'Changed live' not in result.xml_data
    sources = [source.value for row in result.provenance for source in row.sources if isinstance(source.value, Value)]
    assert sources
    assert all(source.snapshot_id == snapshot.pk for source in sources)


def metadata_leaves(value, path=''):
    if is_dataclass(value):
        for field in fields(value):
            yield from metadata_leaves(getattr(value, field.name), f'{path}.{field.name}' if path else field.name)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from metadata_leaves(item, f'{path}[{index}]')
    elif value is not None:
        yield path, value


@pytest.mark.parametrize('kind', ['xml', 'api'])
@pytest.mark.parametrize('version', [None, '', '0'])
def test_bound_scalars_keep_sparse_values_and_format_specific_paths(kind, version):
    metadata = RadarMetadata(
        title='Title', version='0', language='deu',
        software=[Software('Viewer', 'Resource Viewing', version, 'Alternative')],
        funding_references=[FundingReference(award_number='0', award_title='')],
    )
    events = []
    serializer = to_api_payload if kind == 'api' else to_xml_payload
    payload = serializer(metadata, record_output=lambda *event: events.append(event))
    assert payload['title'] == 'Title'
    assert payload['version'] == '0'
    funding, = payload['fundingReferences']['fundingReference']
    if kind == 'api':
        software, = payload['software']['softwareType']
        assert software == {
            'type': 'RESOURCE_VIEWING',
            'softwareName': [{'value': 'Viewer', **({'softwareVersion': version} if version is not None else {})}],
            'alternativeSoftwareName': [{'value': 'Alternative'}],
        }
        assert funding == {'awardNumber': '0', 'awardTitle': ''}
        assert payload['language'] == 'DEU'
        version_path = '/descriptiveMetadata/software/softwareType/0/softwareName/0/softwareVersion'
        funder_path = '/descriptiveMetadata/fundingReferences/fundingReference/0/funderName'
    else:
        software, = payload['software']
        assert software == {
            'type': 'Resource Viewing', 'softwareName': 'Viewer', 'softwareVersion': version,
            'alternativeSoftwareName': 'Alternative', 'alternativeSoftwareVersion': None,
        }
        assert funding == {'funderName': None, 'awardNumber': '0', 'awardURI': None, 'awardTitle': ''}
        assert payload['language'] == 'deu'
        version_path = '/radar:radarDataset/re:software/re:softwareType[1]/re:softwareName/@softwareVersion'
        funder_path = '/radar:radarDataset/re:fundingReferences/re:fundingReference[1]/re:funderName'
    assert ('software[0].version', version_path, version, '') in events
    assert ('funding_references[0].funder_name', funder_path, None, '') in events


@pytest.mark.parametrize('kind', ['xml', 'api'])
def test_all_populated_canonical_fields_have_verified_format_bindings(kind):
    metadata = complete_metadata(
        alternate_identifiers=[Identifier('alternate', 'local')],
        related_identifiers=[Identifier('10.1/related', 'DOI', 'IsSupplementTo')],
        creators=[PersonOrOrganization('Creator', given_name='Given', family_name='Family', name_type='Personal',
                                      identifiers=[Identifier('1234', 'ORCID'), Identifier('5678', 'ISNI')],
                                      affiliations=[Affiliation('Org', 'org-id', 'ROR'), Affiliation('Omitted')])],
        contributors=[PersonOrOrganization('Contributor', name_type='Personal', contributor_type='Other',
                                          affiliations=[Affiliation('Contributor org'), Affiliation('Omitted')])],
        additional_titles=['Extra'], descriptions=[Description('Description')], keywords=['Keyword'],
        publishers=[PersonOrOrganization('Publisher', identifiers=[Identifier('publisher-id', 'ROR')])],
        publication_year='2026', geo_locations=[GeoLocation('Germany', 'Region', 0.0, 10.0)],
        data_sources=[Resource('No type'), Resource('Survey details', 'Survey')],
        software=[Software('Software', 'Resource Viewing', '1', 'Alternative', '2')], processing=['Processing'],
        related_information=['Related'], funding_references=[FundingReference('Funder', Identifier('funder-id', 'ROR'),
                                                                              'Grant', 'https://grant.test', 'Award')],
    )
    provenance = tuple(MappingAttempt(field, (MappingSource('Fixture', value),), value)
                       for field, value in metadata_leaves(metadata))
    factory = build_xml_export_service if kind == 'xml' else build_export_service
    service = factory(None, profile=TEMPLATE_FRAMEWORK_MAPPING, reader=lambda dataset: object(),
                      mapping=lambda context: MappingResult(metadata, provenance=provenance), collect_mapping=True)
    result = service.compute_files([0])[0] if kind == 'xml' else service.compute_payload(0, 'user@example.test')
    assert result.provenance is not None
    assert not any(row.outcome == 'untraced' for row in result.provenance)
    assert any(row.outcome == 'defaulted' for row in result.provenance)
    for field, value in (('latitude', 0.0), ('longitude', 10.0)):
        coordinate, = [row for row in result.provenance if row.field == f'geo_locations[0].{field}']
        assert coordinate.outcome == 'mapped'
        assert coordinate.output_path
        assert coordinate.output_value == (str(value) if kind == 'xml' else value)
    for row in result.provenance:
        if not row.unsuccessful:
            output = xml_leaves(result.xml_data) if kind == 'xml' else dict(json_leaves(result.payload))
            assert output[row.output_path] == row.output_value
    if kind == 'xml':
        for container, prefix, name in (
            ('creators', 'creator', 'Org'), ('contributors', 'contributor', 'Contributor org'),
        ):
            affiliation = next(row for row in result.provenance if row.field == f'{container}[0].affiliations[0].name')
            assert affiliation.outcome == 'mapped'
            assert affiliation.output_path.endswith(f'/re:{prefix}Affiliation[1]')
            assert affiliation.output_value == name
            omitted = next(row for row in result.provenance if row.field == f'{container}[0].affiliations[1].name')
            assert omitted.outcome == 'skipped'
            assert omitted.output_path is None
        identifier = next(row for row in result.provenance if row.field == 'creators[0].affiliations[0].identifier')
        assert identifier.output_path.endswith('/re:creatorAffiliation[1]/@affiliationIdentifier')
        assert identifier.output_value == 'org-id'
        assert any(row.field == 'data_sources[0].value' and row.outcome == 'skipped' for row in result.provenance)
        assert any(row.field == 'data_sources[1].value' and row.output_path.endswith('/re:dataSource[1]')
                   for row in result.provenance)


def test_stale_canonical_trace_is_not_attributed_to_overridden_output():
    metadata = complete_metadata(title='Replacement')
    result = MappingResult(metadata, provenance=(MappingAttempt('title', value='Original'),))
    service = build_export_service(
        None,
        profile=TEMPLATE_FRAMEWORK_MAPPING,
        reader=lambda dataset: object(),
        mapping=lambda context: result,
        collect_mapping=True,
    )
    payload = service.compute_payload(0, 'user@example.test')
    assert payload.provenance[0].outcome == 'skipped'
    row = next(row for row in payload.provenance if row.output_path == '/descriptiveMetadata/title')
    assert row.outcome == 'untraced'
    assert row.output_value == 'Replacement'


@pytest.mark.parametrize('kind', ['xml', 'api'])
def test_custom_serializers_keep_their_existing_signature_and_report_unavailable_provenance(kind):
    serializer = Mock(return_value={})
    factory = build_xml_export_service if kind == 'xml' else build_export_service
    service = factory(
        None,
        profile=TEMPLATE_FRAMEWORK_MAPPING,
        reader=lambda selection: object(),
        serializer=serializer,
        mapping=lambda context: MappingResult(complete_metadata(), provenance=()),
        collect_mapping=True,
    )
    result = service.compute_payload(0, 'user@example.test') if kind == 'api' else service.compute_files([0])[0]
    assert result.provenance is None
    assert 'record_output' not in serializer.call_args.kwargs


@pytest.mark.parametrize('provider_class', [RadarProjectCredentialsExportProvider, RadarProjectExportProvider])
def test_raw_payload_provenance_requires_explicit_hook(provider_class, settings, monkeypatch):
    settings.RADAR_PREVIEW_MAPPING = True
    calls = []
    payload = {'custom': {'field': '<script>Exact</script>'}}

    class ExampleRadarExportProvider(provider_class):
        def get_payload(self, dataset):
            calls.append(dataset.key)
            return payload

    provider = export_provider(ExampleRadarExportProvider)
    monkeypatch.setattr('rdmo_radar.exports.providers.render', lambda request, template, context, status: context)
    result = provider.render_form(provider.get_export_form())
    assert calls == ['0']
    assert not result['dataset_previews'][0]['mapping_preview']['available']

    def provenance(self, dataset, supplied):
        assert supplied is payload
        return (MappingAttempt(
            '/custom/field', (MappingSource('Explicit source', 'Exact'),), supplied['custom']['field'],
            output_path='/custom/field', output_value=supplied['custom']['field'],
        ),)

    monkeypatch.setattr(ExampleRadarExportProvider, 'get_payload_provenance', provenance)
    result = provider.render_form(provider.get_export_form())
    row, = result['dataset_previews'][0]['mapping_preview']['mapped']
    assert row.output_value == payload['custom']['field']
    assert calls == ['0', '0']
    assert provider.request.session.get(provider.get_session_key('request')) is None


@pytest.mark.parametrize('bad', [42, (MappingAttempt('title', output_path='/missing', output_value='Missing'),)])
def test_invalid_custom_provenance_cannot_change_payload(bad, settings, monkeypatch):
    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_MAPPING = True
    provider = export_provider()
    payload = {'descriptiveMetadata': {'title': 'Real'}}
    provider.get_payload = Mock(return_value=payload)
    provider.get_payload_provenance = Mock(return_value=bad)
    # Instance hooks are used by tests; the provider class has the default payload hook.
    monkeypatch.setattr('rdmo_radar.exports.providers.render', lambda request, template, context, status: context)
    result = provider.render_form(provider.get_export_form())
    preview, = result['dataset_previews']
    assert preview['mapping_error']
    assert json.loads(preview['payload_preview']) == payload
    assert not result['form'].errors


def test_raw_trace_json_pointers_and_partial_coverage():
    payload = {'a/b': {'~field': ['Value', None]}}
    row = MappingAttempt('custom', value='Value', output_path='/a~1b/~0field/0', output_value='Value')
    result = validate_payload_provenance((row,), payload)
    assert result[0] is row
    assert result[1].outcome == 'untraced'
    assert result[1].output_value is None
    with pytest.raises(ValueError, match='Provenance does not match the returned payload'):
        validate_payload_provenance((replace(row, output_path='/a~1b/~0field/00'),), payload)


def test_custom_project_mapping_can_record_without_changing_mapping_result_boilerplate(db):
    project = Project.objects.create(title='Project')
    answer = add_answer(project, 'research/title', 'Custom')

    def mapping(context):
        return MappingResult(complete_metadata(title=context.get_text('research/title', target='title')))

    service = build_export_service(
        project, profile=replace(PROJECT_MAPPING, compute_metadata=mapping), collect_mapping=True,
    )
    result = service.compute_payload(ExportDataset('project', 'Project', {'mode': 'project'}), 'user@example.test')
    title = next(row for row in result.provenance if row.field == 'title' and row.output_path)
    assert title.sources[0].value.pk == answer.pk


def test_attribute_and_option_namespace_collisions_are_rejected_with_identifiable_sources(db):
    project = Project.objects.create(title='Project')
    attributes = [add_namespaced_attribute('research/title', prefix)
                  for prefix in ('https://first.test', 'https://second.test')]
    answers = [Value.objects.create(project=project, attribute=attribute, text=f'Title {index}')
               for index, attribute in enumerate(attributes)]
    options = [Option.objects.create(uri_prefix=prefix, uri_path='language/eng', text_lang1='English')
               for prefix in ('https://first.test', 'https://second.test')]
    controlled = [add_answer(project, 'research/language', '', collection_index=index)
                  for index in range(3)]
    for answer, option in zip(controlled, [*options, options[0]], strict=True):
        answer.option = option
        answer.save()
    controlled[-1].text = '0'
    controlled[-1].option = None
    controlled[-1].save()
    context = replace(PROJECT_MAPPING.build_reader(project)(None), provenance=[])
    assert context.get_text('research/title', target='title') is None
    row, = context.provenance
    assert row.outcome == 'rejected'
    assert {source.reference for source in row.sources} == {attribute.uri for attribute in attributes}
    assert context.get_text(attributes[0].uri, target='title') == answers[0].text
    assert context.provenance[-1].sources[0].value.pk == answers[0].pk
    assert context.get_option('research/language', {'language/eng': 'eng'}, target='language') is None
    row = context.provenance[-1]
    assert row.outcome == 'rejected'
    assert {source.value.option.uri for source in row.sources} == {option.uri for option in options}
    assert context.provenance[-2].outcome == 'skipped'
    assert context.provenance[-2].sources[0].value.pk == controlled[-1].pk


def test_license_conflicts_and_title_fallback_have_explicit_attempts(db):
    project = Project.objects.create(title='Project')
    marker = add_answer(project, 'project/dataset/id', 'Dataset ID')
    for index, path in enumerate(list(XMLVocabulary.controlled_rights_options)[:2]):
        option = Option.objects.create(uri_prefix='https://options.test', uri_path=path, text_lang1=f'License {index}')
        answer = add_answer(project, 'project/dataset/sharing/conditions', '', collection_index=index)
        answer.option = option
        answer.save()
    service = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING, collect_mapping=True)
    dataset = ExportDataset('0', 'Dataset', {'set_prefix': '', 'set_index': 0})
    result = service.compute_payload(dataset, 'user@example.test')
    title = next(row for row in result.provenance if row.field == 'title' and row.output_path)
    assert title.outcome == 'defaulted'
    assert title.sources[0].value.pk == marker.pk
    assert title.output_value == 'Dataset ID'
    rights = next(row for row in result.provenance if row.field == 'rights' and row.outcome == 'rejected')
    assert rights.reason == 'Multiple licenses selected'
    assert len(rights.sources) == 2
    assert 'rights' not in result.payload['descriptiveMetadata']


def test_title_fallback_labels_its_decision_even_if_the_reader_records_another_field(monkeypatch):
    from rdmo_radar.mappings.template_framework import fields as tf_fields

    answer = Value(attribute=Attribute(path='project/dataset/id'), text='Fallback title')
    previous = MappingAttempt('title', value='Fallback title', reason='Earlier decision')
    context = ProjectReadContext({'project/dataset/id': [answer]}, {}, provenance=[previous])
    original = tf_fields.read_text

    def read_with_extra_trace(context, **kwargs):
        value = original(context, **kwargs)
        context.record_mapping('resource.value', value='Description', reason='Unrelated reader decision')
        return value

    monkeypatch.setattr(tf_fields, 'read_text', read_with_extra_trace)
    assert tf_fields.read_title(context, target='title') == 'Fallback title'
    assert context.provenance[0] is previous
    titles = [a for a in context.provenance[1:] if a.field == 'title' and not a.unsuccessful]
    assert len(titles) == 1
    assert titles[0].outcome == 'defaulted'
    assert titles[0].reason == 'Dataset ID title fallback'
    assert titles[0].sources[0].value is answer
    assert all(a.outcome == 'mapped' for a in context.provenance if a.field == 'resource.value')


@pytest.mark.parametrize('trace', [False, True])
def test_contributor_rebasing_preserves_diagnostics_sources_and_field_boundaries(trace):
    answer = Value(attribute=Attribute(path='person'), text='Jane Doe')
    source = MappingSource('person', answer)
    previous = MappingAttempt('contributors[1].name', (source,), 'Earlier person')
    previous_issue = MappingIssue('contributors[1].name', 'Earlier issue')
    attempts = [
        previous,
        MappingAttempt('contributors[1].name', (source,), 'Jane Doe'),
        MappingAttempt('contributors[1].identifiers[0].value', (source,), 'id', 'rejected', 'Invalid identifier'),
        MappingAttempt('contributors[2].name', (source,), 'Next person'),
        MappingAttempt('contributors[10].name', (source,), 'Tenth person'),
    ]
    issues = [previous_issue, MappingIssue('contributors[2].name', 'Name warning', source='person')]
    context = ProjectReadContext({}, {}, provenance=attempts if trace else None, issues=issues)
    rebase_mapping(
        context,
        {'contributors[1]': 'contributors[0]', 'contributors[2]': 'contributors[1]'},
        provenance_start=1,
        issue_start=1,
        skipped=('contributors[1]',),
        reason='Duplicate entry',
    )
    assert context.issues == [previous_issue, MappingIssue('contributors[1].name', 'Name warning', source='person')]
    assert context.issues[0] is previous_issue
    if not trace:
        assert context.provenance is None
        return
    assert context.provenance[0] is previous
    duplicate, rejected, following, tenth = context.provenance[1:]
    assert duplicate.field == 'contributors[0].name'
    assert duplicate.outcome == 'skipped'
    assert duplicate.reason == 'Duplicate entry'
    assert rejected.field == 'contributors[0].identifiers[0].value'
    assert rejected.outcome == 'rejected'
    assert rejected.reason == 'Invalid identifier'
    assert following.field == 'contributors[1].name'
    assert following.outcome == 'mapped'
    assert tenth.field == 'contributors[10].name'
    assert tenth.outcome == 'mapped'
    assert all(a.sources[0].value is answer for a in context.provenance)


def test_uninstrumented_custom_mapping_reports_unavailable_and_draft_fallback_is_labelled(db):
    project = Project.objects.create(title='')
    dataset = ExportDataset('project', 'Draft label', {'mode': 'project'})
    service = build_export_service(project, profile=PROJECT_MAPPING, collect_mapping=True)
    result = service.compute_payload(dataset, 'user@example.test')
    row = next(row for row in result.provenance if row.field == 'title' and row.output_path)
    assert row.outcome == 'defaulted'
    assert row.output_value == 'Draft label'
    assert row.sources[0].reference == 'Export dataset label'
    custom = build_export_service(project, profile=PROJECT_MAPPING, collect_mapping=True,
                                  mapping=lambda context: MappingResult(complete_metadata()))
    assert custom.compute_payload(dataset, 'user@example.test').provenance is None


@pytest.mark.parametrize('kind', ['xml', 'api'])
@pytest.mark.parametrize('failure', ['output_binding', 'projection'])
def test_provenance_failures_do_not_change_export_output(traced_project, kind, failure, monkeypatch, caplog):
    factory = build_xml_export_service if kind == 'xml' else build_export_service
    service = factory(
        traced_project,
        profile=TEMPLATE_FRAMEWORK_MAPPING,
        collect_mapping=True,
        **({'clock': lambda: 100} if kind == 'api' else {}),
    )
    dataset = ExportDataset('1', 'Dataset', {'set_prefix': '', 'set_index': 1})
    compute = (lambda: service.compute_files([dataset])[0]) if kind == 'xml' else (
        lambda: service.compute_payload(dataset, 'user@example.test')
    )
    before = compute()

    def failed(*args, **kwargs):
        raise RuntimeError('Private failure detail')

    if failure == 'output_binding':
        original_serializer = service.serializer

        def serialize(metadata, *, record_output, **kwargs):
            def record(field, path, value, reason):
                if field is not None:
                    failed()
                record_output(field, path, value, reason)

            return original_serializer(metadata, record_output=record, **kwargs)

        service.serializer = serialize
    else:
        monkeypatch.setattr('rdmo_radar.services.project_provenance', failed)
    after = compute()
    assert after.provenance is None
    assert (after.xml_data == before.xml_data) if kind == 'xml' else (after.payload == before.payload)
    assert 'error_type=RuntimeError' in caplog.text
    assert 'Private failure detail' not in caplog.text


def test_rest_warnings_and_previews_share_one_prepared_mapping(traced_project, settings, django_assert_num_queries):
    from rdmo_radar.exports import RadarTemplateFrameworkExportProvider as RadarExportProvider

    settings.RADAR_PREVIEW_MAPPING = True
    provider = export_for(traced_project, RadarExportProvider)
    provider.prepare_export_session()
    service = provider.get_service()
    original = service.mapping
    calls = []

    def mapping(context):
        calls.append(context.set_index)
        return original(context)

    service.mapping = mapping
    with django_assert_num_queries(0):
        form = provider.get_export_form()
        previews = provider.compute_dataset_previews(form)
    assert calls == [1, 10]
    assert len(previews) == 2
    assert all(preview['payload_preview'] is None and preview['source_values'] is None for preview in previews)
    assert all(preview['mapping_preview']['available'] for preview in previews)


@pytest.mark.parametrize('provider_class', [RadarCredentialsExportProvider, RadarExportProvider])
@pytest.mark.parametrize('mapping_panel', [False, True])
def test_inline_source_fields_follow_real_payload_indices_without_extra_queries(
    traced_project, settings, django_assert_num_queries, provider_class, mapping_panel,
):
    settings.RADAR_PREVIEW_MAPPING = mapping_panel
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    provider = export_for(traced_project, provider_class)
    provider.prepare_export_session()
    with django_assert_num_queries(0):
        form = provider.get_export_form()
        previews = provider.compute_dataset_previews(form)
    assert form.preview_mapping is mapping_panel
    first, tenth = previews
    for preview in previews:
        title = next(row for row in preview['source_answers']
                     if row['value'].attribute.path == 'project/dataset/title')
        assert title['radar_fields'] == ['descriptiveMetadata.title']
    given_name = next(row for row in first['source_answers']
                      if row['value'].attribute.path == 'project/dataset/creator/given_name')
    assert set(given_name['radar_fields']) == {
        'descriptiveMetadata.creators.creator[0].creatorName',
        'descriptiveMetadata.creators.creator[0].givenName',
        'descriptiveMetadata.creators.creator[0].nameType',
    }
    other = next(row for row in tenth['source_answers']
                 if row['value'].attribute.path == 'project/dataset/creator/name')
    assert other['radar_fields'] == ['descriptiveMetadata.creators.creator[0].creatorName']
    assert other['value'].text == 'Other creator'
    content = render_to_string('plugins/exports_radar_source_answers.html', {
        'source_answers': [given_name], 'mapping_available': True,
    })
    root = ElementTree.fromstring(f'<root>{content}</root>')
    reference = root.find('.//div[@class="radar-attribute-reference"]')
    assert reference.find('./code').text == given_name['value'].attribute.uri
    destinations = reference.findall('./div/div/code')
    assert {field.text for field in destinations} == set(given_name['radar_fields'])


def test_source_fields_match_native_value_identity_not_paths_or_equal_text():
    values = [Value(attribute=Attribute(uri=f'https://{namespace}.test/domain/title', path='title'), text='Same')
              for namespace in ('first', 'second', 'third')]
    payload = {'descriptiveMetadata': {'title': 'Same', 'keywords': {'keyword': [{'value': 'Same'}]}}}
    traces = (
        MappingAttempt('title', (MappingSource('title', values[0]),), value='Same',
                       output_path='/descriptiveMetadata/title', output_value='Same'),
        MappingAttempt('keywords[0]', (MappingSource('title', values[1]),), value='Same',
                       output_path='/descriptiveMetadata/keywords/keyword/0/value', output_value='Same'),
        MappingAttempt('ignored', (MappingSource('title', values[2]),), outcome='rejected'),
    )
    rows = compute_source_answers(values, compute_mapping_preview((*traces, traces[0])), payload=payload)
    assert [row['radar_fields'] for row in rows] == [
        ['descriptiveMetadata.title'], ['descriptiveMetadata.keywords.keyword[0].value'], [],
    ]


@pytest.mark.parametrize('pointer, expected', [
    ('/descriptiveMetadata/title', 'descriptiveMetadata.title'),
    ('/descriptiveMetadata/creators/creator/0/creatorName',
     'descriptiveMetadata.creators.creator[0].creatorName'),
    ('/descriptiveMetadata/a.b/a~1b/~0field', 'descriptiveMetadata["a.b"]["a/b"]["~field"]'),
    ('/descriptiveMetadata/2026', 'descriptiveMetadata["2026"]'),
])
def test_payload_field_paths_preserve_json_keys_and_array_positions(pointer, expected):
    payload = {'descriptiveMetadata': {
        'title': 'Title', 'creators': {'creator': [{'creatorName': 'Person'}]},
        'a.b': {'a/b': {'~field': 'Detail'}}, '2026': 'Year',
    }}
    assert compute_payload_field_path(payload, pointer) == expected


@pytest.mark.parametrize('provenance, expected', [
    (None, 'RADAR field unavailable'), ((), 'No RADAR output recorded for this answer'),
])
def test_missing_inline_provenance_does_not_guess_a_destination(provenance, expected):
    value = Value(attribute=Attribute(uri='https://example.test/domain/title'), text='Title')
    mapping = compute_mapping_preview(provenance)
    rows = compute_source_answers([value], mapping, payload={'descriptiveMetadata': {'title': 'Title'}})
    assert rows[0]['radar_fields'] == []
    content = render_to_string('plugins/exports_radar_source_answers.html', {
        'source_answers': rows, 'mapping_available': mapping['available'],
    })
    assert expected in content
    assert 'descriptiveMetadata.title' not in content


@pytest.fixture
def staff_project(db):
    return make_data_management_project()


def test_default_mapping_explains_disabled_contributors(staff_project):
    add_data_management_role(staff_project, 1)
    service = build_export_service(staff_project, profile=TEMPLATE_FRAMEWORK_MAPPING, collect_mapping=True)
    result = service.compute_payload(1, 'user@example.test')
    assert 'contributors' not in result.payload['descriptiveMetadata']
    source = staff_project.values.get(attribute__path='project/data_management/name')
    rows = compute_source_answers([source], compute_mapping_preview(result.provenance), payload=result.payload)
    assert rows[0]['radar_fields'] == []
    assert rows[0]['mapping_notes'] == [
        {'outcome': 'skipped', 'reason': 'Data-management contributor mapping is disabled'}
    ]


@pytest.mark.parametrize(
    'provider_class',
    [
        RadarCredentialsExportProvider,
        RadarExportProvider,
        RadarExport,
    ],
)
@pytest.mark.parametrize('enabled', [False, True])
def test_source_previews_in_all_exports_explain_optional_sources_without_queries(
    staff_project,
    settings,
    django_assert_num_queries,
    provider_class,
    enabled,
):
    attach_catalog(staff_project)
    shared_page = add_page(staff_project)
    staff = add_questionset(shared_page, 'project/data_management/name', collection=True)
    add_question(staff, 'project/data_management/orcid')
    add_question(staff, 'project/data_management/role')
    add_page(staff_project, 'project/dataset/id', collection=True)
    add_data_management_role(staff_project, 1)
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    provider = export_for(staff_project, provider_class)
    provider.mapping = make_data_management_mapping() if enabled else TEMPLATE_FRAMEWORK_MAPPING
    if provider_class is RadarExport:
        provider.get_service()
        with django_assert_num_queries(0):
            previews = provider.prepare_files()
    else:
        provider.prepare_export_session()
        with django_assert_num_queries(0):
            previews = provider.compute_dataset_previews(provider.get_export_form())
    assert len(previews) == 2
    for preview in previews:
        source = next(
            a for a in preview['source_answers'] if a['value'].attribute.path == 'project/data_management/name'
        )
        if enabled:
            assert any('contributor' in field for field in source['radar_fields'])
        else:
            assert not source['radar_fields']
            assert any('disabled' in note['reason'] for note in source['mapping_notes'])


def test_source_notes_use_native_identity_are_deduplicated_and_escaped():
    from rdmo_radar.metadata.types import MappingAttempt, MappingSource

    first = Value(attribute=Attribute(path='answer'), text='Same')
    other = Value(attribute=Attribute(path='answer'), text='Same')
    attempt = MappingAttempt('contributors', (MappingSource('answer', first),), outcome='skipped', reason='<script>')
    rows = compute_source_answers([first, other], compute_mapping_preview((attempt, attempt)))
    assert len(rows[0]['mapping_notes']) == 1
    assert rows[1]['mapping_notes'] == []
    html = render_to_string(
        'plugins/exports_radar_source_answers.html',
        {
            'source_answers': rows,
            'mapping_available': True,
        },
    )
    assert '&lt;script&gt;' in html
    assert '<script>' not in html
    assert 'No RADAR output recorded for this answer' in html


def test_source_notes_accept_existing_mapping_dictionaries_without_attempts():
    value = Value(attribute=Attribute(path='answer'), text='Available')
    rows = compute_source_answers([value], {'available': True, 'mapped': []})
    assert rows == [{'value': value, 'radar_fields': [], 'mapping_notes': []}]
