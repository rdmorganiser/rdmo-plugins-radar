"""RDMO 2 view contracts: real dispatch and sessions, mocked RADAR HTTP only."""
import io
import json
import zipfile
from urllib.parse import parse_qs, urlsplit

import pytest

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import translation

import requests

from rdmo.projects.models import Project, Snapshot, Value

from .helpers import add_answer, add_attribute

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


def test_project_export_rejects_user_without_object_permission(host):
    project = Project.objects.create(title='Private project', site_id=1)
    user = get_user_model().objects.create_user('outsider', 'other@example.test', 'password')
    host.force_login(user)
    assert host.get(export_url(project)).status_code == 403


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
    result = host.post(url, {'stage': 'export', 'dataset': '1', 'workspace': 'workspace'})
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
    result = host.post(url, {'stage': 'export', 'dataset': '0', 'workspace': 'workspace'})
    assert result.status_code == 200
    assert len(calls) == 2
    assert not project.values.filter(attribute__path='project/dataset/radar_id').exists()
    if status == 401:
        assert b'Log in to RADAR' in result.content
        assert 'rdmo_radar.exports.RadarCredentialsExportProvider.access_token' not in host.session
    else:
        assert result.context['form'].is_bound
        assert host.session['rdmo_radar.exports.RadarCredentialsExportProvider.access_token'] == 'bearer-token'


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
    result = host.post(url, {'stage': 'export', 'dataset': '0', 'workspace': 'workspace'})
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
def test_reconstructed_oauth_callback_without_reader(host, monkeypatch, outcome, raw_payload):
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
    authorization = host.post(url, {'dataset': '0', 'workspace': 'workspace'})
    state = parse_qs(urlsplit(authorization.url).query)['state'][0]
    if raw_payload:
        assert payload_calls == ['0']

    def no_preparation(*args, **kwargs):
        pytest.fail('Callback must not prepare mapping data')

    monkeypatch.setattr('rdmo_radar.exports.providers.build_export_service', no_preparation)
    monkeypatch.setattr('rdmo_radar.mappings.template_framework.fetch_project_values', no_preparation)
    monkeypatch.setattr(RadarExportProvider, 'get_payload', no_preparation)
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
    assert staged_title.pk is None and staged_description.pk is None
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
    result = host.post(url, {'stage': 'export', 'dataset': '0', 'workspace': 'workspace'},
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
    result = host.post(url, {'stage': 'export', 'dataset': selected, 'workspace': 'workspace'})
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
    authorization = host.post(url, {'dataset': selected, 'workspace': 'workspace'})
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
    result = host.post(url, {'stage': 'export', 'dataset': 'record-10-3', 'workspace': 'workspace'})
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
