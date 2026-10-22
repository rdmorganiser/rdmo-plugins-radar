"""RDMO 2 view contracts: real dispatch and sessions, mocked RADAR HTTP only."""
import io
import json
import zipfile
from dataclasses import replace
from itertools import product
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import translation
from django.utils.html import escape

import requests

from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot, Value

from .helpers import add_answer, add_attribute, complete_metadata

pytestmark = pytest.mark.legacy_presentation


@pytest.fixture
def host(settings, db, tmp_path):
    # RDMO 3 removed these legacy project-export views and routes.
    from rdmo.projects import views
    if not hasattr(views, 'ProjectExportView'):
        pytest.skip('RDMO does not expose the legacy export views')
    settings.ROOT_URLCONF = 'tests.urls_host'
    settings.MEDIA_ROOT = str(tmp_path)
    settings.PROJECT_EXPORTS = [
        ('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport'),
        ('radar-credentials', 'RADAR credentials', 'rdmo_radar.exports.RadarCredentialsExportProvider'),
        ('radar-oauth', 'RADAR OAuth', 'rdmo_radar.exports.RadarExportProvider'),
        ('radar-project-xml', 'RADAR project XML', 'rdmo_radar.exports.RadarProjectExport'),
        ('radar-project-credentials', 'RADAR project credentials',
         'rdmo_radar.exports.RadarProjectCredentialsExportProvider'),
        ('radar-project-oauth', 'RADAR project OAuth', 'rdmo_radar.exports.RadarProjectExportProvider'),
        ('radar-custom-xml', 'RADAR custom XML', 'tests.test_mapping_profiles.CustomXmlExport'),
        ('radar-custom-credentials', 'RADAR custom credentials',
         'tests.test_mapping_profiles.CustomCredentialsExportProvider'),
        ('radar-custom-oauth', 'RADAR custom OAuth', 'tests.test_mapping_profiles.CustomOauthExportProvider'),
    ]
    settings.PROJECT_SNAPSHOT_EXPORTS = [settings.PROJECT_EXPORTS[0]]
    settings.PROJECT_IMPORTS = [('radar', 'RADAR', 'rdmo_radar.imports.RadarImport')]
    settings.RADAR_PROVIDER = {
        **settings.RADAR_PROVIDER,
        'redirect_uri': 'http://testserver/services/oauth/radar-oauth/callback/',
    }
    user = get_user_model().objects.create_superuser('owner', 'owner@example.test', 'password')
    client = Client()
    client.force_login(user)
    with translation.override("en"):
        yield client


def response(data, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


def export_url(project, key='radar-xml'):
    return reverse('project_export', args=[project.pk, key])


def test_project_xml_export_uses_native_view_and_warning_download(host):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    warning = host.get(export_url(project))
    assert warning.status_code == 200
    assert 'plugins/exports_radar_xml_validation.html' in [template.name for template in warning.templates]
    assert b'Dataset.xml' in warning.content
    downloaded = host.get(export_url(project), {'download': '1'})
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.namelist() == ['Dataset.xml']
        assert b'<re:title>Dataset</re:title>' in archive.read('Dataset.xml')


def test_snapshot_xml_export_resolves_project_from_native_snapshot_view(host):
    project = Project.objects.create(title='Project')
    live = add_answer(project, 'project/dataset/title', 'Saved dataset')
    snapshot = Snapshot.objects.create(project=project, title='Earlier')
    live.text = 'Current dataset'
    live.save()
    url = reverse('snapshot_export', args=[project.pk, snapshot.pk, 'radar-xml'])
    downloaded = host.get(url, {'download': '1'})
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.namelist() == ['Saved dataset.xml']
        assert b'Current dataset' not in archive.read('Saved dataset.xml')


@pytest.mark.parametrize('key, debug_mode', [
    ('radar-xml', False), ('radar-credentials', True), ('radar-oauth', True),
])
def test_project_export_rejects_user_without_object_permission(host, settings, key, debug_mode):
    settings.RADAR_DEBUG = debug_mode
    project = Project.objects.create(title='Private project', site_id=1)
    user = get_user_model().objects.create_user('outsider', 'other@example.test', 'password')
    host.force_login(user)
    assert host.get(export_url(project, key)).status_code == 403


@pytest.mark.parametrize('authentication', ['credentials', 'oauth'])
@pytest.mark.parametrize('provider_config', [None, {}])
@pytest.mark.parametrize('payload_enabled, sources_enabled, mapping_enabled', product([False, True], repeat=3))
def test_native_debug_form_and_previews_use_real_answers_without_radar_configuration(
    host, settings, monkeypatch, authentication, provider_config, payload_enabled, sources_enabled, mapping_enabled,
):
    settings.RADAR_DEBUG = True
    settings.RADAR_PREVIEW_PAYLOAD = payload_enabled
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = sources_enabled
    settings.RADAR_PREVIEW_MAPPING = mapping_enabled
    if provider_config is None:
        del settings.RADAR_PROVIDER
    else:
        settings.RADAR_PROVIDER = provider_config
    http = Mock(side_effect=AssertionError('Debug mode must not contact RADAR'))
    monkeypatch.setattr(requests, 'get', http)
    monkeypatch.setattr(requests, 'post', http)
    project = Project.objects.create(title='Project')
    title = add_answer(project, 'project/dataset/title', 'Selected dataset', set_index=1)
    add_answer(project, 'project/dataset/title', 'Other dataset', set_index=10)
    before_values = list(project.values.values_list('pk', 'text'))
    url = export_url(project, f'radar-{authentication}')

    opened = host.get(url)

    assert opened.status_code == 200
    content = opened.content.decode()
    assert 'Local RADAR debug mode' in content
    assert 'Local workspace (debug)' in content
    assert 'Selected dataset' in content
    assert 'Other dataset' in content
    assert 'name="csrfmiddlewaretoken"' in content
    assert 'value="Export to RADAR"' not in content
    assert 'name="preview"' not in content
    assert 'name="cancel"' in content
    assert 'name="username"' not in content
    assert not any(key.endswith(('.access_token', '.workspace_choices')) for key in host.session.keys())
    session = dict(host.session)
    previews = opened.context['dataset_previews']
    assert [preview['dataset'].key for preview in previews] == ['1', '10']
    assert all(preview['warnings'] for preview in previews)
    form_position = content.index('<form method="post" action="" novalidate>')
    assert content.index('class="radar-dataset-preview"') < form_position
    assert content.rindex('</section>') < form_position
    if payload_enabled or sources_enabled or mapping_enabled:
        assert not opened.context['form'].errors
        assert 'Preview from current answers' in content
        if payload_enabled:
            payload = json.loads(previews[0]['payload_preview'])
            assert payload['descriptiveMetadata']['title'] == title.text
            assert 'technicalMetadata' in payload
            assert json.loads(previews[1]['payload_preview'])['descriptiveMetadata']['title'] == 'Other dataset'
        if sources_enabled:
            assert [value.pk for value in previews[0]['source_values']] == [title.pk]
            assert title.attribute.uri in content
            assert 'RDMO Attributes and answers' in content
            assert 'class="radar-attribute-coordinates"' in content
            assert '<code class="text-muted">descriptiveMetadata.title</code>' in content
        assert ('<summary>RADAR Field mapping</summary>' in content) == mapping_enabled
        if mapping_enabled:
            mapped = previews[0]['mapping_preview']['mapped']
            row = next(row for row in mapped if row.field == 'title')
            assert row.sources[0].value.pk == title.pk
            assert row.output_path == '/descriptiveMetadata/title'
            assert row.output_value == title.text
            assert previews[0]['mapping_preview']['attempts']
            assert 'Empty, skipped, and rejected attempts' in content
            assert 'title="set_prefix"' in content
    else:
        assert 'Preview from current answers' not in content
        assert all(preview['payload_preview'] is None and preview['source_values'] is None for preview in previews)

    blocked = host.post(url, {'export': '1', 'stage': 'export', 'dataset': '1', 'workspace': 'local-workspace'})
    assert blocked.status_code == 200
    assert b'RADAR export is disabled in local debug mode.' in blocked.content
    assert dict(host.session) == session
    assert list(project.values.values_list('pk', 'text')) == before_values
    http.assert_not_called()


@pytest.mark.parametrize('payload_enabled, sources_enabled, mapping_enabled', product([False, True], repeat=3))
def test_valid_xml_preview_flags_are_independent_and_download_remains_xml_only(
    host, settings, monkeypatch, payload_enabled, sources_enabled, mapping_enabled,
):
    from rdmo_radar.exports import RadarProjectExport
    from rdmo_radar.mappings.project import PROJECT_MAPPING
    from rdmo_radar.metadata.types import MappingResult

    settings.RADAR_PREVIEW_PAYLOAD = payload_enabled
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = sources_enabled
    settings.RADAR_PREVIEW_MAPPING = mapping_enabled
    settings.DEBUG = True  # Coordinate visibility follows RADAR_DEBUG instead.
    calls = []

    def mapping(context):
        calls.append(context.provenance is not None)
        title = context.get_text('research/title', target='title')
        return MappingResult(complete_metadata(title=title))

    monkeypatch.setattr(RadarProjectExport, 'mapping', replace(PROJECT_MAPPING, compute_metadata=mapping))
    project = Project.objects.create(title='Project')
    answer = add_answer(project, 'research/title', 'Complete dataset')
    before_values = list(project.values.values_list('pk', 'text'))
    before_session = dict(host.session)
    url = export_url(project, 'radar-project-xml')
    opened = host.get(url)
    assert opened.status_code == 200
    if payload_enabled or sources_enabled or mapping_enabled:
        assert opened['Content-Type'].startswith('text/html')
        assert b'RADAR XML export preview' in opened.content
        assert b'Download XML' in opened.content
        assert not opened.context['has_warnings']
        assert not opened.context['debug_mode']
        assert b'set_prefix' not in opened.content
        file, = opened.context['files']
        assert file['payload_preview'] == (file['xml_data'].decode() if payload_enabled else None)
        assert file['source_values'] == ([answer] if sources_enabled else None)
        assert file['mapping_preview']['available'] == (mapping_enabled or sources_enabled)
        if sources_enabled:
            assert b'<summary>RDMO Attributes and answers</summary>' in opened.content
            assert b'class="list-group radar-attribute-answers"' in opened.content
            assert file['source_answers'][0]['radar_fields'] == ['/radar:radarDataset/re:title[1]']
            assert b'<code class="text-muted">/radar:radarDataset/re:title[1]</code>' in opened.content
        assert (b'<summary>RADAR Field mapping</summary>' in opened.content) == mapping_enabled
        if mapping_enabled:
            title = next(row for row in file['mapping_preview']['mapped'] if row.field == 'title')
            assert title.output_path.endswith('/re:title[1]')
            assert title.sources[0].value.pk == answer.pk
            assert any(row.outcome == 'untraced' for row in file['mapping_preview']['mapped'])
            if sources_enabled:
                assert file['source_answers'][0]['radar_fields'] == ['/radar:radarDataset/re:title[1]']
    else:
        assert opened['Content-Type'] == 'application/zip'
    assert calls == [mapping_enabled or sources_enabled]

    # Direct downloads skip every preview helper and the provenance collector.
    def no_preview(*args):
        pytest.fail('Download must not prepare preview answers')

    monkeypatch.setattr(RadarProjectExport, 'get_source_values', no_preview)
    downloaded = host.get(url, {'download': '1'})
    assert calls == [mapping_enabled or sources_enabled, False]
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.namelist() == ['Complete dataset.xml']
        xml = archive.read('Complete dataset.xml')
        assert b'<re:title>Complete dataset</re:title>' in xml
        assert b'provenance' not in xml
        if payload_enabled:
            assert xml == file['xml_data']
    assert list(project.values.values_list('pk', 'text')) == before_values
    assert dict(host.session) == before_session


def test_xml_snapshot_previews_keep_dataset_associations_and_escape_all_panels(host, settings):
    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    settings.RADAR_PREVIEW_MAPPING = True
    settings.RADAR_DEBUG = True
    project = Project.objects.create(title='Project')
    title = '<script>Saved é</script>'
    for index in (1, 10):
        add_answer(project, 'project/dataset/title', title, set_index=index)
    snapshot = Snapshot.objects.create(project=project, title='<b>Saved answers</b>')
    project.values.filter(snapshot=None).update(text='Current answer')
    url = reverse('snapshot_export', args=[project.pk, snapshot.pk, 'radar-xml'])
    opened = host.get(url)
    files = opened.context['files']
    assert len(files) == 2
    assert len({file['file_name'] for file in files}) == 2
    assert [file['dataset'].key for file in files] == ['1', '10']
    assert opened.context['has_warnings']
    assert opened.context['debug_mode']
    content = opened.content.decode()
    assert 'Preview from snapshot' in content
    assert str(escape(snapshot.title)) in content
    assert 'Preview from current answers' not in content
    assert 'Current answer' not in content
    assert title not in content
    assert str(escape(title)) in content
    assert '&amp;lt;script&amp;gt;' in content  # The actual generated XML is escaped for HTML too.
    assert 'class="radar-attribute-coordinates"' in content
    assert 'title="set_prefix"' in content
    for index, file in zip((1, 10), files, strict=True):
        assert file['has_warnings']
        assert file['source_values'][0].set_index == index
        row = next(row for row in file['mapping_preview']['mapped'] if row.field == 'title')
        source = row.sources[0].value
        assert source.snapshot_id == snapshot.pk
        assert source.set_index == index
        assert row.output_value == title


@pytest.mark.parametrize('authentication', ['credentials', 'oauth'])
def test_debug_project_export_has_one_dataset_and_cancel_keeps_native_redirect(
    host, settings, monkeypatch, authentication,
):
    settings.RADAR_DEBUG = True
    del settings.RADAR_PROVIDER
    http = Mock(side_effect=AssertionError('Debug mode must not contact RADAR'))
    monkeypatch.setattr(requests, 'get', http)
    monkeypatch.setattr(requests, 'post', http)
    project = Project.objects.create(title='No dataset collections')
    project_url = export_url(project, f'radar-project-{authentication}')
    opened = host.get(project_url)
    assert list(opened.context['form'].fields['dataset'].choices) == [('project', project.title)]

    # Debug mode retains each profile's discovery semantics.
    template_framework = host.get(export_url(project, f'radar-{authentication}'))
    assert list(template_framework.context['form'].fields['dataset'].choices) == []
    canceled = host.post(project_url, {'cancel': '1', 'export': '1'})
    assert canceled.status_code == 302
    assert canceled.url == reverse('project', args=[project.pk])
    http.assert_not_called()


@pytest.mark.parametrize('authentication', ['credentials', 'oauth'])
def test_django_debug_alone_keeps_normal_authentication(host, settings, monkeypatch, authentication):
    settings.DEBUG = True
    assert not getattr(settings, 'RADAR_DEBUG', False)
    http = Mock(return_value=response({}, status=401))
    monkeypatch.setattr(requests, 'get', http)
    project = Project.objects.create(title='Project')
    opened = host.get(export_url(project, f'radar-{authentication}'))
    if authentication == 'credentials':
        assert opened.status_code == 200
        assert b'name="username"' in opened.content
        assert b'Local RADAR debug mode' not in opened.content
    else:
        assert opened.status_code == 302
        assert '/oauth/authorize?' in opened.url
    http.assert_not_called()


@pytest.mark.parametrize('method', ['get', 'post'])
def test_native_oauth_callback_cannot_resume_a_request_in_debug_mode(host, settings, monkeypatch, method):
    settings.RADAR_DEBUG = True
    del settings.RADAR_PROVIDER
    http = Mock(side_effect=AssertionError('Debug callback must not exchange tokens or replay requests'))
    monkeypatch.setattr(requests, 'get', http)
    monkeypatch.setattr(requests, 'post', http)
    prefix = 'rdmo_radar.exports.RadarExportProvider.'
    pending = [method, 'https://radar.example.test/radar/api/workspaces']
    if method == 'post':
        pending += [{'technicalMetadata': {}, 'descriptiveMetadata': {'title': 'Queued'}}, None, None]
    session = host.session
    for key, value in (
        ('request', pending), ('state', 'pending-state'), ('operation', 'create_dataset'),
        ('export_context', {'persist': True}), ('access_token', 'existing-token'),
    ):
        session[prefix + key] = value
    session.save()
    before_values = list(Value.objects.values_list('pk', 'text'))

    result = host.get(reverse('oauth_callback', args=['radar-oauth']), {
        'state': 'pending-state', 'code': 'authorization-code',
    })

    assert result.status_code == 200
    assert b'Local RADAR debug mode' in result.content
    assert b'authentication and export are disabled' in result.content
    for key in ('request', 'state', 'operation', 'export_context'):
        assert prefix + key not in host.session
    assert host.session[prefix + 'access_token'] == 'existing-token'
    assert list(Value.objects.values_list('pk', 'text')) == before_values
    http.assert_not_called()


def credentials_login(host, project, monkeypatch, *, creation_status=201, key='radar-credentials'):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith('/tokens'):
            return response({'access_token': 'bearer-token'})
        return response({'id': 'confirmed'}, creation_status)

    monkeypatch.setattr('rdmo_radar.client.requests.post', post)
    monkeypatch.setattr('rdmo_radar.client.requests.get', lambda *args, **kwargs: response({
        'data': [{'id': 'workspace', 'descriptiveMetadata': {'title': 'Workspace'}}],
    }))
    url = export_url(project, key)
    assert host.get(url).status_code == 200
    login = host.post(url, {'stage': 'credentials', 'username': 'radar-user', 'password': 'radar-password'})
    assert login.status_code == 302
    assert host.get(url).status_code == 200
    return url, calls


def test_credentials_export_native_forms_and_scoped_storage(host, monkeypatch):
    project = Project.objects.create(title='Project')
    snapshot = Snapshot.objects.create(project=project, title='Saved')
    add_answer(project, 'project/dataset/title', 'Dataset', set_index=1)
    saved = add_answer(project, 'project/dataset/radar_id', 'saved-id', set_index=1, snapshot=snapshot)
    add_attribute('project/dataset/radar_url')
    nested = add_answer(project, 'project/dataset/radar_id', 'nested-id', set_index=1, set_prefix='1')
    other_collection = add_answer(project, 'project/dataset/radar_id', 'collection-id', set_index=1, collection_index=1)
    url, calls = credentials_login(host, project, monkeypatch)
    result = host.post(url, {'export': '1', 'stage': 'export', 'dataset': '1', 'workspace': 'workspace'})
    assert result.status_code == 302
    assert result.url == 'https://radar.example.test/radar/en/dataset/confirmed'
    assert len(calls) == 2
    assert calls[1][1]['json']['descriptiveMetadata']['title'] == 'Dataset'
    for value, text in ((saved, 'saved-id'), (nested, 'nested-id'), (other_collection, 'collection-id')):
        value.refresh_from_db()
        assert value.text == text
    assert project.values.get(attribute__path='project/dataset/radar_id', snapshot=None,
                              set_prefix='', set_index=1, collection_index=0).text == 'confirmed'
    assert not any(key.startswith('rdmo_radar.exports.RadarCredentialsExportProvider.') for key in host.session.keys())


@pytest.mark.parametrize('status', [401, 403, 422, 500])
def test_credentials_native_failure_preserves_form_or_requests_login(host, monkeypatch, status):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    add_attribute('project/dataset/radar_id')
    url, calls = credentials_login(host, project, monkeypatch, creation_status=status)
    result = host.post(url, {'export': '1', 'stage': 'export', 'dataset': '0', 'workspace': 'workspace'})
    assert result.status_code == 200
    assert len(calls) == 2
    assert not project.values.filter(attribute__path='project/dataset/radar_id').exists()
    if status == 401:
        assert b'Log in to RADAR' in result.content
        assert 'rdmo_radar.exports.RadarCredentialsExportProvider.access_token' not in host.session
    else:
        assert result.context['form'].is_bound
        assert host.session['rdmo_radar.exports.RadarCredentialsExportProvider.access_token'] == 'bearer-token'


@pytest.mark.parametrize('authentication', ['credentials', 'oauth'])
@pytest.mark.parametrize('status, expected', [
    (422, 'RADAR rejected the dataset metadata:'),
    (404, 'The RADAR resource or API endpoint could not be found.'),
    (500, 'RADAR reported a server error.'),
    (503, 'RADAR reported a server error.'),
])
@pytest.mark.parametrize('detail', [
    'Es existiert bereits ein Eintrag mit dem gleichen Namen auf dieser Ebene.',
    'Ungültiger Name: <script>alert("name")</script>',
])
def test_export_displays_radar_error(host, monkeypatch, authentication, status, expected, detail):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    calls = []

    def post(url, *args, **kwargs):
        calls.append(url)
        if url.endswith('/tokens') or '/oauth/token' in url:
            return response({'access_token': 'bearer-token'})
        return response({'exception': f'Validation exception: {detail}'}, status)

    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response({
        'data': [{'id': 'workspace', 'descriptiveMetadata': {'title': 'Workspace'}}],
    }))
    key = f'radar-{authentication}'
    url = export_url(project, key)
    started = host.get(url)
    if authentication == 'credentials':
        assert started.status_code == 200
        login = host.post(url, {'stage': 'credentials', 'username': 'radar-user', 'password': 'radar-password'})
        assert login.status_code == 302
    else:
        state = parse_qs(urlsplit(started.url).query)['state'][0]
        callback = reverse('oauth_callback', args=[key])
        assert host.get(callback, {'state': state, 'code': 'workspace-code'}).status_code == 302
    assert host.get(url).status_code == 200

    if authentication == 'oauth':
        # Exercise failure after core replays the saved creation POST.
        session = host.session
        del session['rdmo_radar.exports.RadarExportProvider.access_token']
        session.save()
    result = host.post(url, {'export': '1', 'stage': 'export', 'dataset': '0', 'workspace': 'workspace'})
    if authentication == 'oauth':
        state = parse_qs(urlsplit(result.url).query)['state'][0]
        result = host.get(callback, {'state': state, 'code': 'creation-code'})
    else:
        assert result.context['form'].is_bound
        assert result.context['form'].cleaned_data['dataset'] == '0'
        assert result.context['form'].cleaned_data['workspace'] == 'workspace'
    assert result.status_code == 200
    content = result.content.decode()
    assert expected in content
    if status == 422:
        assert str(escape(detail)) in content
    else:
        assert str(escape(detail)) not in content
    if status >= 500:
        assert 'Check RADAR for an existing draft before retrying' in content
    assert '<script>alert(' not in content
    assert sum('/datasets' in target for target in calls) == 1
    assert not project.values.filter(attribute__path='project/dataset/radar_id').exists()


@pytest.mark.parametrize('authentication', ['credentials', 'oauth'])
@pytest.mark.parametrize('payload_enabled, sources_enabled', [
    (False, False), (True, False), (False, True), (True, True),
])
def test_native_automatic_previews_are_display_only_and_export_prepares_fresh_payload(
    host, monkeypatch, settings, authentication, payload_enabled, sources_enabled,
):
    from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExportProvider

    settings.RADAR_PREVIEW_PAYLOAD = payload_enabled
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = sources_enabled
    project = Project.objects.create(title='Project')
    title = add_answer(project, 'project/dataset/title', '<script>Selected é</script>', set_index=1)
    add_answer(project, 'project/dataset/title', 'Other dataset', set_index=10)
    option = Option.objects.create(uri_prefix='https://options.test', uri_path='example/type',
                                   text_lang1='<b>Option label</b>', additional_input=True)
    answer = add_answer(project, 'project/dataset/language', 'Answer <em>text</em>', set_index=1)
    answer.option = option
    answer.external_id = '<external-id>'
    answer.save()
    for path in ('project/dataset/radar_id', 'project/dataset/radar_url'):
        add_attribute(path)
    payload_calls = []
    requests_sent = []
    provider_class = RadarCredentialsExportProvider if authentication == 'credentials' else RadarExportProvider

    def get_payload(provider, dataset):
        payload_calls.append(dataset.key)
        return {
            'technicalMetadata': {'archiveDate': len(payload_calls)},
            'descriptiveMetadata': {'title': provider.get_context(dataset).get_text('project/dataset/title')},
        }

    def post(url, *args, **kwargs):
        if url.endswith('/tokens') or '/oauth/token' in url:
            return response({'access_token': 'bearer-token'})
        requests_sent.append(kwargs['json'])
        return response({'id': 'confirmed'}, 201)

    monkeypatch.setattr(provider_class, 'get_payload', get_payload)
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: response({
        'data': [{'id': 'workspace', 'descriptiveMetadata': {'title': 'Workspace'}}],
    }))
    key = f'radar-{authentication}'
    url = export_url(project, key)
    started = host.get(url)
    if authentication == 'credentials':
        assert host.post(url, {'stage': 'credentials', 'username': 'user', 'password': 'password'}).status_code == 302
    else:
        state = parse_qs(urlsplit(started.url).query)['state'][0]
        assert host.get(reverse('oauth_callback', args=[key]), {'state': state, 'code': 'code'}).status_code == 302
    result = host.get(url)
    assert b'name="preview"' not in result.content
    assert b'name="export"' in result.content
    assert b'name="csrfmiddlewaretoken"' in result.content
    assert not result.context['form'].is_bound
    assert list(project.values.filter(attribute__path='project/dataset/radar_id')) == []
    assert payload_calls == (['1', '10'] if payload_enabled or sources_enabled else [])
    assert not requests_sent
    content = result.content.decode()
    previews = result.context['dataset_previews']
    if payload_enabled or sources_enabled:
        assert 'Preview from current answers' in content
        assert 'subsequently edited answers may differ' in content
        assert [preview['dataset'].key for preview in previews] == ['1', '10']
        form_position = content.index('<form method="post" action="" novalidate>')
        assert content.index('class="radar-dataset-preview"') < form_position
        assert content.rindex('</section>') < form_position
        if payload_enabled:
            assert json.loads(previews[0]['payload_preview'])['descriptiveMetadata']['title'] == title.text
            assert json.loads(previews[1]['payload_preview'])['descriptiveMetadata']['title'] == 'Other dataset'
            assert str(escape(title.text)) in content
        if sources_enabled:
            values = previews[0]['source_values']
            assert {value.pk for value in values} == {title.pk, answer.pk}
            assert answer.attribute.uri in content
            assert option.uri in content
            for text in (answer.text, option.text, answer.external_id):
                assert str(escape(text)) in content
            assert 'Other dataset' not in [value.text for value in values]
            assert content.count('class="radar-attribute-header"') == 3  # One card per Value across both datasets.
            assert '<summary>RDMO Attributes and answers</summary>' in content
            assert '<summary>Attribute URI</summary>' not in content
            assert 'scope="col"' not in content  # Only answer previews are enabled in this test.
            assert '<pre>Answer' not in content
            assert 'class="radar-attribute-coordinates"' not in content
            for name in ('set_prefix', 'set_index', 'collection_index'):
                assert f'title="{name}"' not in content
                assert f'aria-label="{name}:' not in content
            assert 'rdmo_radar/css/exports.css' in content
        else:
            assert 'RDMO Attributes and answers' not in content
        assert title.text not in content
        assert '<b>Option label</b>' not in content
    else:
        assert previews == []
        assert 'Preview from current answers' not in content

    title.text = 'Changed after preview'
    title.save()
    exported = host.post(url, {'export': '1', 'stage': 'export', 'dataset': '1', 'workspace': 'workspace'})
    assert exported.status_code == 302
    assert len(requests_sent) == 1
    assert payload_calls == (['1', '10', '1'] if payload_enabled or sources_enabled else ['1'])
    assert requests_sent[0] == {
        'technicalMetadata': {'archiveDate': len(payload_calls)},
        'descriptiveMetadata': {'title': 'Changed after preview'},
    }
    assert project.values.get(attribute__path='project/dataset/radar_id').text == 'confirmed'



def test_project_preview_displays_empty_payload_and_answers(host, monkeypatch, settings):
    from rdmo_radar.exports import RadarProjectCredentialsExportProvider

    settings.RADAR_PREVIEW_PAYLOAD = True
    settings.RADAR_PREVIEW_SOURCE_ANSWERS = True
    project = Project.objects.create(title='No answers')
    monkeypatch.setattr(RadarProjectCredentialsExportProvider, 'get_payload', lambda *args: {})
    url, _ = credentials_login(host, project, monkeypatch, key='radar-project-credentials')
    no_post = Mock(side_effect=AssertionError('Automatic preview must not submit a request'))
    monkeypatch.setattr(requests, 'post', no_post)
    result = host.get(url)
    assert result.status_code == 200
    preview, = result.context['dataset_previews']
    assert preview['dataset'].key == 'project'
    assert preview['payload_preview'] == '{}'
    assert preview['source_values'] == []
    assert b'<pre>{}</pre>' in result.content
    assert b'No RDMO answers were found in the selected scope.' in result.content
    no_post.assert_not_called()


def test_credentials_local_failure_shows_confirmation_and_rolls_back(host, monkeypatch):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    add_attribute('project/dataset/radar_id')
    add_attribute('project/dataset/radar_url')
    url, calls = credentials_login(host, project, monkeypatch)
    save = Value.save

    def fail_url(value, *args, **kwargs):
        if value.attribute.path == 'project/dataset/radar_url':
            raise RuntimeError('Private database detail')
        return save(value, *args, **kwargs)

    monkeypatch.setattr(Value, 'save', fail_url)
    result = host.post(url, {'export': '1', 'stage': 'export', 'dataset': '0', 'workspace': 'workspace'})
    assert b'RADAR dataset created' in result.content
    assert b'https://radar.example.test/radar/en/dataset/confirmed' in result.content
    assert b'Private database detail' not in result.content
    assert b'name="workspace"' not in result.content
    assert b'name="dataset"' not in result.content
    assert not project.values.filter(attribute__path__startswith='project/dataset/radar_').exists()
    assert len(calls) == 2


def test_oauth_export_with_callback_on_another_deployment_shows_configuration_error(host, settings, monkeypatch):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    settings.RADAR_PROVIDER = {
        **settings.RADAR_PROVIDER,
        'redirect_uri': 'https://staging.example.test/services/oauth/radar-oauth/callback/',
    }

    def no_remote_request(*args, **kwargs):
        pytest.fail('An export with a callback on another deployment must not contact RADAR')

    monkeypatch.setattr('rdmo.services.providers.requests.get', no_remote_request)
    monkeypatch.setattr('rdmo.services.providers.requests.post', no_remote_request)

    result = host.get(export_url(project, 'radar-oauth'))

    assert result.status_code == 200
    assert b'RADAR OAuth configuration error' in result.content
    assert b'different RDMO instance' in result.content
    assert 'Location' not in result
    assert 'rdmo_radar.exports.RadarExportProvider.state' not in host.session


@pytest.mark.parametrize('raw_payload', [False, True])
@pytest.mark.parametrize('outcome', [
    'success', 'http_error', 'malformed', 'storage_error', 'missing_project', 'missing_context',
    'canceled', 'context_removed_during_token', 'context_removed_during_post',
])
def test_reconstructed_oauth_callback_without_reader(host, monkeypatch, settings, outcome, raw_payload):
    from rdmo_radar.exports import RadarExportProvider

    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    add_attribute('project/dataset/radar_id')
    add_attribute('project/dataset/radar_url')
    calls = []
    payload_calls = []
    payload = {'technicalMetadata': {}, 'descriptiveMetadata': {'title': 'Custom request'}}
    if raw_payload:
        def get_payload(provider, dataset):
            payload_calls.append(dataset.key)
            return payload

        monkeypatch.setattr(RadarExportProvider, 'get_payload', get_payload)

    def post(url, *args, **kwargs):
        calls.append((url, kwargs))
        if '/oauth/token' in url:
            return response({'access_token': 'oauth-token'})
        return response({} if outcome == 'malformed' else {'id': 'confirmed'},
                        500 if outcome == 'http_error' else 201)

    monkeypatch.setattr('rdmo.services.providers.requests.post', post)
    monkeypatch.setattr('rdmo.services.providers.requests.get', lambda *args, **kwargs: response({
        'data': [{'id': 'workspace', 'descriptiveMetadata': {'title': 'Workspace'}}],
    }))
    url = export_url(project, 'radar-oauth')
    authorized = host.get(url)
    state = parse_qs(urlsplit(authorized.url).query)['state'][0]
    callback = reverse('oauth_callback', args=['radar-oauth'])
    assert host.get(callback, {'state': state, 'code': 'workspace-code'}).status_code == 302
    assert host.get(url).status_code == 200
    # Reauthorize creation so core stores/replays the POST in a reconstructed provider.
    session = host.session
    del session['rdmo_radar.exports.RadarExportProvider.access_token']
    session.save()
    authorization = host.post(url, {'export': '1', 'dataset': '0', 'workspace': 'workspace'})
    state = parse_qs(urlsplit(authorization.url).query)['state'][0]
    if raw_payload:
        assert payload_calls == ['0']
    queued = host.session['rdmo_radar.exports.RadarExportProvider.request'][2]
    assert set(queued) == {'technicalMetadata', 'descriptiveMetadata'}
    settings.RADAR_PREVIEW_MAPPING = True

    def no_preparation(*args, **kwargs):
        pytest.fail('Callback must not prepare mapping data')

    monkeypatch.setattr('rdmo_radar.exports.providers.build_export_service', no_preparation)
    monkeypatch.setattr('rdmo_radar.mappings.template_framework.fetch_project_values', no_preparation)
    monkeypatch.setattr(RadarExportProvider, 'get_payload', no_preparation)
    monkeypatch.setattr(RadarExportProvider, 'get_payload_provenance', no_preparation)
    # The saved operation, rather than later form state, identifies the destination.
    session = host.session
    session['rdmo_radar.exports.RadarExportProvider.project_id'] = 999999
    if outcome == 'missing_context':
        del session['rdmo_radar.exports.RadarExportProvider.export_context']
    session.save()
    if outcome == 'canceled':
        assert host.post(url, {'cancel': '1'}).status_code == 302
        for key in ('request', 'state', 'operation', 'export_context'):
            assert f'rdmo_radar.exports.RadarExportProvider.{key}' not in host.session
    elif outcome == 'context_removed_during_token':
        store = RadarExportProvider.store_in_session

        def remove_context(provider, request, key, data):
            store(provider, request, key, data)
            if key == 'access_token':
                provider.pop_from_session(request, 'export_context')

        monkeypatch.setattr(RadarExportProvider, 'store_in_session', remove_context)
    elif outcome == 'context_removed_during_post':
        post_success = RadarExportProvider.post_success

        def remove_context_after_creation(provider, request, response):
            provider.pop_from_session(request, 'export_context')
            return post_success(provider, request, response)

        monkeypatch.setattr(RadarExportProvider, 'post_success', remove_context_after_creation)
    if outcome == 'missing_project':
        project.delete()
    elif outcome == 'storage_error':
        save = Value.save

        def fail_url(value, *args, **kwargs):
            if value.attribute.path == 'project/dataset/radar_url':
                raise RuntimeError('Private database detail')
            return save(value, *args, **kwargs)

        monkeypatch.setattr(Value, 'save', fail_url)
    result = host.get(callback, {'state': state, 'code': 'creation-code'})
    blocked = outcome in ('missing_context', 'canceled', 'context_removed_during_token')
    assert len(calls) == (2 if outcome == 'context_removed_during_token' else 1 if blocked else 3)
    if raw_payload and not blocked:
        assert calls[-1][1]['json'] == payload
        assert payload_calls == ['0']
    if outcome == 'canceled':
        # Core dispatch requires a saved OAuth state and returns its generic
        # integration error after cancellation has removed that state.
        assert result.status_code == 500
        assert b'Integration Error' in result.content
        assert not Value.objects.filter(attribute__path='project/dataset/radar_id').exists()
    elif blocked:
        assert result.status_code == 200
        assert b'incomplete or was canceled' in result.content
        assert not Value.objects.filter(attribute__path='project/dataset/radar_id').exists()
        assert not any('/datasets' in target for target, _ in calls)
    elif outcome in ('success', 'context_removed_during_post'):
        assert result.status_code == 302
        assert result.url == 'https://radar.example.test/radar/en/dataset/confirmed'
        assert project.values.get(attribute__path='project/dataset/radar_id').text == 'confirmed'
    else:
        assert result.status_code == 200
        assert b'Private database detail' not in result.content
        assert not Value.objects.filter(attribute__path='project/dataset/radar_id').exists()
        if outcome in ('storage_error', 'missing_project'):
            assert b'RADAR dataset created' in result.content
            assert b'https://radar.example.test/radar/en/dataset/confirmed' in result.content
            assert b'name="workspace"' not in result.content
        else:
            assert b'Check RADAR for an existing draft' in result.content
    if outcome not in ('http_error', 'malformed'):
        assert 'rdmo_radar.exports.RadarExportProvider.export_context' not in host.session


def test_credentials_post_requires_csrf_token(host, monkeypatch):
    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(get_user_model().objects.get(username='owner'))
    url = export_url(project, 'radar-credentials')
    assert protected.get(url).status_code == 200
    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        return response({'access_token': 'token'})

    monkeypatch.setattr('rdmo_radar.client.requests.post', post)
    data = {'stage': 'credentials', 'username': 'radar-user', 'password': 'radar-password'}
    assert protected.post(url, data).status_code == 403
    assert calls == []
    token = protected.cookies['csrftoken'].value
    assert protected.post(url, data, HTTP_X_CSRFTOKEN=token).status_code == 302
    assert len(calls) == 1


def test_import_upload_preview_apply_uses_native_checked_value_lifecycle(host):
    from rdmo.questions.models import Catalog, CatalogSection, Page, PageQuestion, Question, Section, SectionPage

    catalog = Catalog.objects.create(
        uri_prefix='https://example.test', uri_path='import-catalog', title_lang1='Catalog',
    )
    section = Section.objects.create(
        uri_prefix='https://example.test', uri_path='import-section', title_lang1='Section',
    )
    CatalogSection.objects.create(catalog=catalog, section=section, order=0)
    title = add_attribute('project/dataset/title')
    description = add_attribute('project/dataset/description')
    page = Page.objects.create(uri_prefix='https://example.test', uri_path='import-page', attribute=title,
                               title_lang1='Dataset', is_collection=True)
    SectionPage.objects.create(section=section, page=page, order=0)
    for index, attribute in enumerate((title, description)):
        question = Question.objects.create(uri_prefix='https://example.test', uri_path=f'import-question-{index}',
                                           attribute=attribute, text_lang1='Answer', widget_type='text')
        PageQuestion.objects.create(page=page, question=question, order=index)
    project = Project.objects.create(title='Project', catalog=catalog)
    add_answer(project, 'project/dataset/title', 'Existing')
    url = reverse('project_update_import', args=[project.pk])
    xml = b'''<radar:radarDataset
      xmlns:radar="http://radar-service.eu/schemas/descriptive/radar/v09/radar-dataset"
      xmlns:re="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
      <re:title>Imported title</re:title>
      <re:resource resourceType="Dataset">Imported description</re:resource>
    </radar:radarDataset>'''
    uploaded = host.post(url, {'method': 'upload_file', 'uploaded_file': SimpleUploadedFile('radar.xml', xml)})
    assert uploaded.status_code == 302
    before = list(project.values.values())
    preview = host.get(url)
    assert preview.status_code == 200
    assert list(project.values.values()) == before
    values = preview.context['values']
    staged_title = next(value for value in values if value.attribute.path == 'project/dataset/title')
    staged_description = next(value for value in values if value.attribute.path == 'project/dataset/description')
    assert staged_title.pk is None
    assert staged_description.pk is None
    assert staged_title.set_index == staged_description.set_index == 1
    checked = f'{staged_title.attribute.uri}[{staged_title.set_prefix}][1][{staged_title.collection_index}]'
    applied = host.post(url, {'method': 'import_file', checked: 'on'})
    assert applied.status_code == 302
    assert applied.url == project.get_absolute_url()
    assert project.values.get(attribute=title, set_index=1).text == 'Imported title'
    assert not project.values.filter(attribute=description).exists()


@pytest.mark.parametrize('language', ['en', 'de'])
def test_credentials_uses_actual_client_instance_for_dataset_link(host, monkeypatch, language):
    from rdmo_radar.client import RadarClient
    from rdmo_radar.exports.credentials import RadarCredentialsExportProvider

    project = Project.objects.create(title='Project')
    add_answer(project, 'project/dataset/title', 'Dataset')
    add_attribute('project/dataset/radar_url')
    url, calls = credentials_login(host, project, monkeypatch)
    staging = RadarClient('https://staging.example.test', 'client', 'secret', 'https://rdmo.example.test/')
    monkeypatch.setattr(RadarCredentialsExportProvider, 'client', property(lambda self: staging))
    result = host.post(url, {'export': '1', 'stage': 'export', 'dataset': '0', 'workspace': 'workspace'},
                       HTTP_ACCEPT_LANGUAGE=language)
    expected = f'https://staging.example.test/radar/{language}/dataset/confirmed'
    assert result.url == expected
    assert calls[-1][0].startswith('https://staging.example.test/')
    assert project.values.get(attribute__path='project/dataset/radar_url').text == expected


def make_custom_project():
    from .helpers import add_namespaced_attribute

    project = Project.objects.create(title='Project')
    attribute = add_namespaced_attribute('research/title', 'https://custom.test')
    add_namespaced_attribute('research/radar_id', 'https://custom.test')
    add_namespaced_attribute('research/radar_url', 'https://custom.test')
    for parent, name in ((1, 'First record'), (10, 'Second record')):
        Value.objects.create(project=project, attribute=attribute, text=name, set_prefix=str(parent), set_index=3)
    return project


def test_project_and_custom_xml_exports_dispatch_through_native_registration(host):
    project = Project.objects.create(title='Project record')
    warning = host.get(export_url(project, 'radar-project-xml'))
    assert warning.status_code == 200
    assert b'Project record.xml' in warning.content
    downloaded = host.get(export_url(project, 'radar-project-xml'), {'download': '1'})
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.namelist() == ['Project record.xml']
        assert b'<re:title>Project record</re:title>' in archive.read('Project record.xml')
    assert not project.values.exists()
    project = make_custom_project()
    downloaded = host.get(export_url(project, 'radar-custom-xml'), {'download': '1'})
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.namelist() == ['First record.xml', 'Second record.xml']
        assert b'<re:title>Second record</re:title>' in archive.read('Second record.xml')


def example_request_payload(provider, dataset):
    context = provider.get_context(dataset)
    return {
        'technicalMetadata': {
            'retentionPeriod': 3, 'archiveDate': 1234, 'publishDate': 4321,
            'responsibleEmail': provider.request.user.email, 'schema': {'key': 'RDDM', 'version': '9.3'},
        },
        'descriptiveMetadata': {
            'title': f"Direct {context.get_text('research/title') or provider.project.title}",
            'keywords': {'keyword': [{'value': 'Custom request'}]},
        },
        'customField': {'enabled': False, 'values': [0, None]},
    }


@pytest.mark.parametrize('raw_payload', [False, True])
@pytest.mark.parametrize('mode', ['project', 'custom', 'storage_error'])
def test_credentials_profiles_use_opaque_keys_and_selected_persistence(host, monkeypatch, mode, raw_payload):
    from dataclasses import replace

    from rdmo_radar.exports import RadarProjectCredentialsExportProvider

    from .test_mapping_profiles import CUSTOM_MAPPING, CustomCredentialsExportProvider

    if mode == 'project':
        project = Project.objects.create(title='Project record')
        add_attribute('project/dataset/radar_id')
        add_attribute('project/dataset/radar_url')
        key, selected, title = 'radar-project-credentials', 'project', 'Project record'
        cls = RadarProjectCredentialsExportProvider
    else:
        project = make_custom_project()
        key, selected, title = 'radar-custom-credentials', 'record-10-3', 'Second record'
        cls = CustomCredentialsExportProvider
    if mode == 'storage_error':
        def fail(*args):
            raise RuntimeError('Private database detail')
        monkeypatch.setattr(CustomCredentialsExportProvider, 'mapping', replace(CUSTOM_MAPPING, store_result=fail))
    payload_calls = []
    if raw_payload:
        def get_payload(provider, dataset):
            payload = example_request_payload(provider, dataset)
            payload_calls.append((dataset, payload))
            return payload

        def no_mapping(*args, **kwargs):
            pytest.fail('Canonical metadata mapping called for a raw payload')

        monkeypatch.setattr(cls, 'get_payload', get_payload)
        monkeypatch.setattr(cls, 'mapping', replace(cls.mapping, compute_metadata=no_mapping))
    url, calls = credentials_login(host, project, monkeypatch, key=key)
    assert payload_calls == []
    result = host.post(url, {'export': '1', 'stage': 'export', 'dataset': selected, 'workspace': 'workspace'})
    assert len(calls) == 2
    if raw_payload:
        assert len(payload_calls) == 1
        assert payload_calls[0][0].key == selected
        assert calls[1][1]['json'] == payload_calls[0][1]
        assert calls[1][1]['json']['descriptiveMetadata']['title'] == f'Direct {title}'
    else:
        assert calls[1][1]['json']['descriptiveMetadata']['title'] == title
    if mode == 'storage_error':
        assert result.status_code == 200
        assert b'https://radar.example.test/radar/en/dataset/confirmed' in result.content
        assert b'Private database detail' not in result.content
        assert b'name="workspace"' not in result.content
    else:
        assert result.status_code == 302
        assert result.url == 'https://radar.example.test/radar/en/dataset/confirmed'
    if mode == 'custom':
        stored = project.values.get(attribute__uri='https://custom.test/domain/research/radar_url')
        assert (stored.set_prefix, stored.set_index, stored.text) == ('10', 3, result.url)
    elif mode == 'project':
        assert not project.values.exists()
    else:
        assert not project.values.filter(attribute__path='research/radar_url').exists()


@pytest.mark.parametrize('raw_payload', [False, True])
@pytest.mark.parametrize('mode', ['project', 'custom', 'storage_error'])
def test_reconstructed_oauth_profiles_preserve_scope_and_optional_storage_without_readers(
    host, monkeypatch, mode, raw_payload,
):
    from dataclasses import replace

    from rdmo_radar.exports import RadarProjectExportProvider

    from .test_mapping_profiles import CUSTOM_MAPPING, CustomOauthExportProvider

    if mode == 'project':
        project = Project.objects.create(title='Project record')
        add_attribute('project/dataset/radar_id')
        add_attribute('project/dataset/radar_url')
        key, selected, title = 'radar-project-oauth', 'project', 'Project record'
        cls = RadarProjectExportProvider
        class_name = 'rdmo_radar.exports.RadarProjectExportProvider'
    else:
        project = make_custom_project()
        key, selected, title = 'radar-custom-oauth', 'record-10-3', 'Second record'
        cls = CustomOauthExportProvider
        class_name = 'tests.test_mapping_profiles.CustomOauthExportProvider'
    if mode == 'storage_error':
        def fail(*args):
            raise RuntimeError('Private database detail')
        monkeypatch.setattr(cls, 'mapping', replace(CUSTOM_MAPPING, store_result=fail))
    payload_calls = []
    if raw_payload:
        def get_payload(provider, dataset):
            payload = example_request_payload(provider, dataset)
            payload_calls.append((dataset, payload))
            return payload

        def no_mapping(*args, **kwargs):
            pytest.fail('Canonical metadata mapping called for a raw payload')

        monkeypatch.setattr(cls, 'get_payload', get_payload)
        monkeypatch.setattr(cls, 'mapping', replace(cls.mapping, compute_metadata=no_mapping))
    calls = []

    def post(url, *args, **kwargs):
        calls.append((url, args, kwargs))
        return response({'access_token': 'oauth-token'} if '/oauth/token' in url else {'id': 'confirmed'})

    monkeypatch.setattr('rdmo.services.providers.requests.post', post)
    monkeypatch.setattr('rdmo.services.providers.requests.get', lambda *args, **kwargs: response({
        'data': [{'id': 'workspace', 'descriptiveMetadata': {'title': 'Workspace'}}],
    }))
    url = export_url(project, key)
    authorized = host.get(url)
    state = parse_qs(urlsplit(authorized.url).query)['state'][0]
    callback = reverse('oauth_callback', args=[key])
    assert host.get(callback, {'state': state, 'code': 'workspace-code'}).status_code == 302
    form = host.get(url)
    assert form.status_code == 200
    assert title.encode() in form.content
    assert payload_calls == []
    if raw_payload:
        assert b'Missing required metadata' not in form.content
    session = host.session
    del session[f'{class_name}.access_token']
    session.save()
    authorization = host.post(url, {'export': '1', 'dataset': selected, 'workspace': 'workspace'})
    state = parse_qs(urlsplit(authorization.url).query)['state'][0]
    captured = host.session[f'{class_name}.export_context']
    assert captured['dataset']['key'] == selected
    assert captured['provider'] == class_name
    if raw_payload:
        assert len(payload_calls) == 1
        assert payload_calls[0][0].key == selected
        assert host.session[f'{class_name}.request'][2] == payload_calls[0][1]

    def no_preparation(*args, **kwargs):
        pytest.fail('OAuth persistence must not prepare metadata readers')

    monkeypatch.setattr(cls, 'mapping', replace(cls.mapping, build_reader=no_preparation, get_datasets=no_preparation,
                                              compute_metadata=no_preparation))
    monkeypatch.setattr('rdmo_radar.exports.providers.build_export_service', no_preparation)
    monkeypatch.setattr(cls, 'get_payload', no_preparation)
    session = host.session
    session[f'{class_name}.project_id'] = 999999
    session[f'{class_name}.dataset_choices'] = [('wrong-record', 'Changed form')]
    session.save()
    if mode == 'project':
        # Omitted persistence remains success even if its former project disappears.
        project.delete()
    result = host.get(callback, {'state': state, 'code': 'creation-code'})
    assert len(calls) == 3
    if raw_payload:
        assert calls[-1][2]['json'] == payload_calls[0][1]
        assert calls[-1][2]['json']['descriptiveMetadata']['title'] == f'Direct {title}'
    else:
        assert calls[-1][2]['json']['descriptiveMetadata']['title'] == title
    if mode == 'storage_error':
        assert result.status_code == 200
        assert b'https://radar.example.test/radar/en/dataset/confirmed' in result.content
        assert b'Private database detail' not in result.content
        assert b'name="workspace"' not in result.content
    else:
        assert result.status_code == 302
        assert result.url == 'https://radar.example.test/radar/en/dataset/confirmed'
    if mode == 'custom':
        stored = project.values.get(attribute__uri='https://custom.test/domain/research/radar_url')
        assert (stored.set_prefix, stored.set_index, stored.text) == ('10', 3, result.url)
    assert f'{class_name}.export_context' not in host.session


def test_stale_dataset_is_rejected_before_remote_creation(host, monkeypatch):
    project = make_custom_project()
    url, calls = credentials_login(host, project, monkeypatch, key='radar-custom-credentials')
    project.values.filter(attribute__uri='https://custom.test/domain/research/title', set_prefix='10').delete()
    result = host.post(url, {'export': '1', 'stage': 'export', 'dataset': 'record-10-3', 'workspace': 'workspace'})
    assert result.status_code == 200
    assert b'no longer available' in result.content
    assert len(calls) == 1


def test_project_and_template_framework_sessions_coexist(host, monkeypatch):
    project = Project.objects.create(title='Project record')
    add_answer(project, 'project/dataset/title', 'Dataset')
    credentials_login(host, project, monkeypatch)
    credentials_login(host, project, monkeypatch, key='radar-project-credentials')
    session = host.session
    assert session['rdmo_radar.exports.RadarCredentialsExportProvider.dataset_choices'] == [['0', 'Dataset']]
    assert session['rdmo_radar.exports.RadarProjectCredentialsExportProvider.dataset_choices'] == [
        ['project', 'Project record'],
    ]
