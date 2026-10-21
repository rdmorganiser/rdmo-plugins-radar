"""Automatic dataset previews share prepared Values without exporting or changing sessions."""
import json
from copy import deepcopy
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from django.template.loader import render_to_string

from rdmo.core.constants import VALUE_TYPE_BOOLEAN, VALUE_TYPE_DATETIME
from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot, Value

from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExportProvider, RadarProjectExportProvider
from rdmo_radar.exports.previews import compute_source_answers
from rdmo_radar.mappings import ExportDataset
from rdmo_radar.metadata.types import MappingAttempt, MappingResult, MappingSource, RadarMetadata

from .helpers import add_answer, add_namespaced_attribute, export_for, template_framework_context
from .test_exports import export_provider


@pytest.fixture(params=[RadarCredentialsExportProvider, RadarExportProvider])
def preview_provider(request, monkeypatch):
    provider = export_provider(request.param)
    provider.get_datasets = lambda: [ExportDataset(str(index), 'Dataset', {'set_index': index}) for index in (1, 10)]
    provider.prepare_export_session()
    provider.get_payload = Mock(return_value={})
    provider.get_source_values = Mock(return_value=[])
    http = Mock(side_effect=AssertionError('Preview must not contact RADAR'))
    monkeypatch.setattr('requests.get', http)
    monkeypatch.setattr('requests.post', http)
    monkeypatch.setattr('rdmo_radar.exports.providers.render', lambda request, template, context, status: context)
    yield provider
    http.assert_not_called()


@pytest.mark.parametrize('payload_enabled, sources_enabled', [
    (False, False), (True, False), (False, True), (True, True),
])
def test_preview_flags_are_independent_and_preserve_session(
    preview_provider, settings, payload_enabled, sources_enabled,
):
    settings.RADAR_PREVIEW_PAYLOAD = payload_enabled
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = sources_enabled
    provider = preview_provider
    for key, value in (('state', 'existing-state'), ('operation', 'existing-operation'),
                       ('request', ['get', 'existing-request'])):
        provider.store_in_session(provider.request, key, value)
    session = deepcopy(provider.request.session)

    # Form construction and validation must not run payload/source preview hooks.
    form = provider.get_export_form()
    provider.get_payload.assert_not_called()
    provider.get_source_values.assert_not_called()
    result = provider.render_form(form)

    assert provider.request.session == session
    assert not result['form'].is_bound
    assert not result['form'].errors
    assert provider.get_payload.call_count == 2 * int(payload_enabled or sources_enabled)
    assert provider.get_source_values.call_count == 2 * int(sources_enabled)
    assert [preview['dataset'].key for preview in result['dataset_previews']] == ['1', '10']
    for preview in result['dataset_previews']:
        assert preview['source_values'] == ([] if sources_enabled else None)
        assert preview['payload_preview'] == ('{}' if payload_enabled else None)
        assert preview['warnings'][0]['dataset_key'] == preview['dataset'].key
        assert preview['warnings'][0]['title'] == 'Dataset'
        assert not preview['payload_error']
        assert not preview['source_error']


def test_preview_settings_default_to_disabled_but_keep_dataset_warnings(preview_provider):
    provider = preview_provider
    result = provider.render_form(provider.get_export_form())
    assert not result['form'].preview_payload
    assert not result['form'].preview_source_answers
    assert len(result['dataset_previews']) == 2
    assert all(preview['warnings'] for preview in result['dataset_previews'])
    provider.get_payload.assert_not_called()
    provider.get_source_values.assert_not_called()


@pytest.mark.parametrize('selection', [{}, {'dataset': 'removed'}, {'workspace': 'unlisted'}])
def test_previews_do_not_require_valid_form_selections(preview_provider, settings, selection):
    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    provider = preview_provider
    form = provider.get_export_form(data=selection)
    assert not form.is_valid()
    provider.get_payload.assert_not_called()
    provider.get_source_values.assert_not_called()
    result = provider.render_form(form)
    assert len(result['dataset_previews']) == 2
    assert provider.get_payload.call_count == 2
    assert provider.get_source_values.call_count == 2


@pytest.mark.parametrize('failed_panel', ['payload', 'source_values'])
def test_failed_preview_is_isolated_to_its_dataset_and_panel(preview_provider, settings, failed_panel, caplog):
    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    provider = preview_provider

    def prepare(dataset):
        if dataset.key == '1':
            raise RuntimeError('Private preparation detail')
        return {} if failed_panel == 'payload' else []

    hook = provider.get_payload if failed_panel == 'payload' else provider.get_source_values
    hook.side_effect = prepare
    result = provider.render_form(provider.get_export_form())
    assert not result['form'].errors
    failed, valid = result['dataset_previews']
    assert failed['payload_error' if failed_panel == 'payload' else 'source_error']
    assert failed['source_values'] == (None if failed_panel == 'source_values' else [])
    assert failed['payload_preview'] == (None if failed_panel == 'payload' else '{}')
    assert valid['payload_preview'] == '{}'
    assert valid['source_values'] == []
    assert not valid['payload_error']
    assert not valid['source_error']
    assert 'Private preparation detail' not in str(result)
    assert 'Private preparation detail' not in caplog.text
    assert 'error_type=RuntimeError' in caplog.text


@pytest.mark.parametrize('payload', [None, [], {'invalid': float('nan')}, {'invalid': object()}])
def test_automatic_preview_rejects_invalid_payloads_without_invalidating_form(preview_provider, settings, payload):
    settings.RADAR_PREVIEW_PAYLOAD = True
    provider = preview_provider
    provider.get_payload.return_value = payload
    result = provider.render_form(provider.get_export_form())
    assert not result['form'].errors
    assert all(preview['payload_error'] and preview['payload_preview'] is None
               for preview in result['dataset_previews'])


def test_source_only_preview_keeps_answers_when_payload_preparation_fails(preview_provider, settings):
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    provider = preview_provider
    answer = Value(attribute=Attribute(uri='https://example.test/domain/title'), text='Available answer')
    provider.get_source_values.return_value = [answer]
    provider.get_payload.return_value = {'invalid': float('nan')}
    result = provider.render_form(provider.get_export_form())
    assert not result['form'].errors
    for preview in result['dataset_previews']:
        assert preview['mapping_error']
        assert preview['source_error'] is None
        assert preview['source_values'] == [answer]
        assert preview['source_answers'] == [{'value': answer, 'radar_fields': []}]


def test_mapping_warning_failure_does_not_hide_other_dataset_warnings(preview_provider, caplog):
    provider = preview_provider

    def mapping(context):
        if context.set_index == 1:
            raise RuntimeError('Private mapping detail')
        return MappingResult(RadarMetadata(title='Dataset'))

    provider.get_service().mapping = mapping
    result = provider.render_form(provider.get_export_form())
    failed, valid = result['dataset_previews']
    assert failed['warnings'][0]['error']
    assert valid['warnings'][0]['missing']
    assert 'Private mapping detail' not in str(result)
    assert 'Private mapping detail' not in caplog.text
    assert not result['form'].errors


def test_custom_warnings_use_dataset_keys_when_titles_repeat(preview_provider):
    provider = preview_provider
    warnings = [{
        'dataset_key': key, 'title': 'Dataset', 'missing': [f'Requirement {key}'], 'issues': (),
    } for key in ('10', '1')]
    provider.get_mapping_warnings = lambda: warnings
    result = provider.render_form(provider.get_export_form())
    first, second = result['dataset_previews']
    assert first['warnings'] == [warnings[1]]
    assert second['warnings'] == [warnings[0]]


@pytest.mark.parametrize('old_preview', [False, True])
def test_submission_without_export_action_cannot_create_a_dataset(preview_provider, old_preview):
    provider = preview_provider
    provider.request.POST.pop('export')
    provider.request.POST['dataset'] = '1'
    if old_preview:
        provider.request.POST['preview'] = '1'
    assert provider.get_export_form(data=provider.request.POST).is_valid()
    session = deepcopy(provider.request.session)
    result = provider.submit()
    assert result['form'].is_bound
    assert provider.request.session == session
    provider.get_payload.assert_not_called()


def test_cancel_takes_priority_over_preparing_previews(preview_provider, settings, monkeypatch):
    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    provider = preview_provider
    provider.request.POST['cancel'] = '1'
    provider.get_export_form = Mock(side_effect=AssertionError('Cancellation prepared a form'))
    for module in ('providers', 'credentials'):
        monkeypatch.setattr(f'rdmo_radar.exports.{module}.redirect', lambda *args: args)
    assert provider.submit() == ('project', 1)
    provider.get_payload.assert_not_called()
    provider.get_source_values.assert_not_called()


def test_empty_dataset_list_does_not_invent_previews(preview_provider, settings):
    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    provider = preview_provider
    provider.get_datasets = lambda: []
    assert provider.render_form(provider.get_export_form())['dataset_previews'] == []
    provider.get_payload.assert_not_called()
    provider.get_source_values.assert_not_called()


def test_all_dataset_previews_reuse_prepared_values_without_queries(db, settings, django_assert_num_queries):
    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    project = Project.objects.create(title='Project')
    markers = [add_answer(project, 'project/dataset/title', f'Dataset {index}', set_index=index) for index in (1, 10)]
    provider = export_for(project, RadarExportProvider)
    provider.prepare_export_session()
    form = provider.get_export_form()
    with django_assert_num_queries(0):
        previews = provider.compute_dataset_previews(form)
    assert [json.loads(preview['payload_preview'])['descriptiveMetadata']['title'] for preview in previews] == [
        marker.text for marker in markers
    ]
    assert [preview['source_values'] for preview in previews] == [[marker] for marker in markers]


def test_source_values_keep_identity_coordinates_and_snapshot_without_queries(db, django_assert_num_queries):
    project = Project.objects.create(title='No catalog')
    snapshot = Snapshot.objects.create(project=project, title='Saved answers')
    attributes = [add_namespaced_attribute('research/type', prefix)
                  for prefix in ('https://first.test', 'https://second.test')]
    option = Option.objects.create(uri_prefix='https://options.test', uri_path='type/example', text_lang1='Example')
    saved = [Value.objects.create(project=project, snapshot=snapshot, attribute=attribute, option=option,
                                  text=f'Answer {index}', external_id=f'ID-{index}',
                                  set_prefix=str(index), set_index=10, collection_index=index)
             for index, attribute in enumerate(attributes)]
    Value.objects.create(project=project, attribute=attributes[0], text='Live answer')
    provider = export_for(project, RadarProjectExportProvider)
    provider.snapshot = snapshot
    dataset = provider.get_datasets()[0]
    with django_assert_num_queries(0):
        values = provider.get_source_values(dataset)
        assert provider.get_context(dataset).get_scope_values() == saved
        assert values == saved
        assert [value.attribute.uri for value in values] == [attribute.uri for attribute in attributes]
        assert [value.option.text for value in values] == ['Example', 'Example']
        assert [value.option.uri for value in values] == [option.uri, option.uri]
        assert [value.external_id for value in values] == ['ID-0', 'ID-1']
        assert [(value.set_prefix, value.set_index, value.collection_index) for value in values] == [
            ('0', 10, 0), ('1', 10, 1),
        ]


def test_source_values_respect_selected_flat_scope_and_do_not_expand_shared_answers(db, django_assert_num_queries):
    project = Project.objects.create(title='Project')
    markers = [add_answer(project, 'project/dataset/title', f'Dataset {index}', set_index=index) for index in (1, 10)]
    creators = [add_answer(project, 'project/dataset/creator/name', f'Creator {index}', set_prefix=str(index))
                for index in (1, 10)]
    add_answer(project, 'project/funder/name', 'Shared funder', set_index=7)
    provider = export_for(project, RadarExportProvider)
    datasets = provider.get_datasets()
    with django_assert_num_queries(0):
        for dataset, marker, creator in zip(datasets, markers, creators, strict=True):
            assert provider.get_source_values(dataset) == [creator, marker]


def test_source_values_accept_prepared_synthetic_attributes_without_a_shared_none_identity():
    attribute = Attribute(path='project/dataset/title')
    value = Value(attribute=attribute, text='Synthetic answer', set_index=10)
    provider = RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarExportProvider')
    provider.get_context = lambda dataset: template_framework_context({attribute.path: [value]}, set_index=10)
    assert provider.get_source_values(None) == [value]


@pytest.mark.parametrize('debug_mode', [False, True])
def test_answer_cards_preserve_native_value_display_and_debug_coordinates(debug_mode):
    uri = 'https://example.test/terms/domain/' + 'long_attribute_name/' * 12 + 'title'
    attribute = Attribute(uri=uri)
    text = 'First line\n<script>Text & details</script>'
    option = Option(uri='https://example.test/options/example', text_lang1='<b>Option label</b>', additional_input=True)
    values = [
        Value(attribute=attribute, text=text, set_prefix='', set_index=0, collection_index=0, snapshot_id=17),
        Value(attribute=attribute, option=option, text='Extra input', unit='kg', external_id='<external-id>',
              set_prefix='1|0|10', set_index=10, collection_index=2, snapshot_id=17),
        Value(attribute=attribute, text='42', unit='m'),
        Value(attribute=attribute, text='0', value_type=VALUE_TYPE_BOOLEAN),
        Value(attribute=attribute, text='2026-10-19', value_type=VALUE_TYPE_DATETIME),
        Value(attribute=attribute, file='project/files/report.csv'),
        Value(attribute=attribute, external_id='external-only'),
    ]
    expected = [text, '<b>Option label</b>: Extra input kg', '42 m', 'No', 'Oct. 19, 2026', 'report.csv', None]
    content = render_to_string('plugins/exports_radar_source_answers.html', {
        'source_answers': compute_source_answers(values), 'debug_mode': debug_mode,
    })
    root = ElementTree.fromstring(f'<root>{content}</root>')
    cards = root.findall('./ul/li')
    assert len(cards) == len(values)
    assert root.find('.//table') is None
    for card, value, answer in zip(cards, values, expected, strict=True):
        header = card.find('./div')
        assert header.find('./div/code').text == uri
        assert header.find('./div/code').get('class') == 'code-domain'
        badges = header.findall('./div/span')
        if debug_mode:
            assert [badge.text for badge in badges] == [f'"{value.set_prefix}"', str(value.set_index),
                                                       str(value.collection_index)]
            for badge, name in zip(badges, ('set_prefix', 'set_index', 'collection_index'), strict=True):
                assert badge.get('title') == name
                assert badge.get('aria-label') == f'{name}: {getattr(value, name)}'
                assert badge.get('tabindex') == '0'
                assert badge.get('data-toggle') is None
        else:
            assert badges == []
        assert card.find('./div[@class="radar-source-text"]').text == answer
    option_uri = cards[1].find('./div[@class="radar-source-details"]/div/code')
    assert option_uri.text == option.uri
    assert option_uri.get('class') == 'code-options'
    assert '<external-id>' in ''.join(cards[1].itertext())
    assert 'External ID: external-only' in ''.join(cards[-1].itertext())
    assert cards[0].find('./div[@class="radar-source-details"]') is None
    assert 'Snapshot:' not in ''.join(root.itertext())
    assert root.find('.//details') is None
    assert root.find('.//script') is None
    assert root.find('.//b') is None

    mapping_content = render_to_string('plugins/exports_radar_mapping_rows.html', {
        'rows': [MappingAttempt('title', sources=(MappingSource(uri, value),)) for value in values],
        'debug_mode': debug_mode,
    })
    mapping_root = ElementTree.fromstring(f'<root>{mapping_content}</root>')
    rows = mapping_root.findall('./ul/li')
    assert len(rows) == len(values)
    assert mapping_root.find('.//table') is None
    for row, value, answer in zip(rows, values, expected, strict=True):
        source = row.find('./div[@class="radar-mapping-source"]')
        assert source.find('./div[@class="radar-source-text"]').text == answer
        if value.snapshot_id:
            details = source.find('./div[@class="radar-source-details"]')
            assert 'Snapshot: 17' in ''.join(details.itertext())
        else:
            assert 'Snapshot:' not in ''.join(source.itertext())
        badges = source.findall('.//div[@class="radar-attribute-coordinates"]/span')
        assert len(badges) == (3 if debug_mode else 0)
    assert rows[1].find('.//code[@class="code-options"]').text == option.uri
    assert 'External ID: external-only' in ''.join(rows[-1].itertext())
    assert mapping_root.find('.//script') is None
    assert mapping_root.find('.//b') is None
