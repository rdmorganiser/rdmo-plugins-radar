import io
import json
import zipfile
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings

import requests

from rdmo.services.providers import OauthProviderMixin

from rdmo_radar.exceptions import RadarProtocolError
from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExportProvider
from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import (
    get_radar_schema,
    get_radar_validation_errors,
    validate_radar_xml,
)
from rdmo_radar.mappings import ExportDataset
from rdmo_radar.metadata.constants import APIVocabulary, XMLVocabulary
from rdmo_radar.metadata.types import MappingResult, RadarMetadata

from .helpers import add_answer, complete_metadata, configure_service, dataset_payload, make_export, read_metadata


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError('Private upstream error', response=response)


def make_provider(post=None, provider_class=RadarCredentialsExportProvider):
    class_name = f'rdmo_radar.exports.{provider_class.__name__}'
    provider = configure_service(provider_class('radar', 'RADAR', class_name))
    provider.request = SimpleNamespace(
        POST=post or {},
        GET={},
        session={},
        user=SimpleNamespace(email='user@example.test'),
        LANGUAGE_CODE='en'
    )
    provider.project = SimpleNamespace(id=1, pk=1)
    provider.get_datasets = lambda: []
    return provider


def prepare_oauth_creation(provider):
    request = provider.request
    request.GET = {'state': 'expected-state', 'code': 'authorization-code'}
    context = {
        'project_id': provider.project.pk, 'provider': provider.class_name, 'persist': False,
        'radar_url': provider.radar_url, 'language': 'de',
        'dataset': {'key': 'dataset:10|3', 'label': 'Dataset', 'scope': {'set_prefix': '10', 'set_index': 3}},
    }
    provider.store_in_session(request, 'export_context', context)
    provider.store_in_session(request, 'operation', 'create_dataset')
    provider.store_in_session(request, 'state', 'expected-state')
    provider.store_in_session(request, 'request', (
        'post', f'{provider.radar_url}/radar/api/workspaces/workspace/datasets',
        {'technicalMetadata': {}, 'descriptiveMetadata': {'title': 'Dataset'}}, None, None,
    ))
    return context


def make_valid_xml_dataset(**overrides):
    dataset = {
        'identifier': '10.1234/example',
        'identifierType': 'DOI',
        'creators': {'creator': [{'creatorName': 'Doe, Jane'}]},
        'title': 'Dataset',
        'publishers': {'publisher': ['Example Repository']},
        'productionYear': '2026',
        'language': 'eng',
        'subjectAreas': {'subjectArea': [{'controlledSubjectAreaName': 'Chemistry'}]},
        'resource': {'value': 'Research data', 'resourceType': 'Dataset'},
        'rights': {'controlledRights': 'CC BY 4.0 Attribution'},
        'rightsHolders': {'rightsHolder': ['Example University']},
        'version': '1.0'
    }
    dataset.update(overrides)
    return dataset


def test_oauth_provider_uses_authorization_code_configuration():
    provider = make_provider(provider_class=RadarExportProvider)

    assert isinstance(provider, OauthProviderMixin)
    assert provider.authorize_url == 'https://radar.example.test/radar-backend/oauth/authorize'
    assert provider.token_url == 'https://radar.example.test/radar-backend/oauth/token'
    assert provider.get_authorize_params(None, 'state') == {
        'response_type': 'code',
        'client_id': 'configured-client-id',
        'redirect_uri': 'https://rdmo.example.test/services/oauth/radar/callback/',
        'state': 'state'
    }
    assert provider.get_callback_auth(None) == ('configured-client-id', 'client-secret')
    assert provider.get_callback_data(None) == {}


@override_settings(ALLOWED_HOSTS=['rdmo.example.test'])
def test_oauth_render_redirects_and_preserves_workspace_request():
    provider = make_provider(provider_class=RadarExportProvider)
    provider.request = RequestFactory().get('/', secure=True, HTTP_HOST='rdmo.example.test')
    provider.request.session = {}

    response = provider.render()

    query = parse_qs(urlparse(response.url).query)
    assert response.status_code == 302
    assert query['client_id'] == ['configured-client-id']
    assert query['redirect_uri'] == ['https://rdmo.example.test/services/oauth/radar/callback/']
    assert provider.get_get_url() == 'https://radar.example.test/radar/api/workspaces'
    assert provider.get_from_session(provider.request, 'request') == (
        'get', 'https://radar.example.test/radar/api/workspaces',
    )
    assert provider.get_from_session(provider.request, 'state') == query['state'][0]


@pytest.mark.parametrize(('host', 'secure'), [
    ('localhost:8000', False),
    ('staging.example.test', True),
    ('rdmo.example.test:8443', True),
    ('rdmo.example.test', False),
])
def test_oauth_authorization_rejects_callback_on_different_origin(monkeypatch, host, secure):
    provider = make_provider(provider_class=RadarExportProvider)
    request = RequestFactory().get('/', secure=secure, HTTP_HOST=host)
    request.session = {}
    monkeypatch.setattr('rdmo_radar.exports.providers.render',
                        lambda request, template, context, status: (template, context, status))

    with override_settings(ALLOWED_HOSTS=[host.split(':')[0]]):
        template, context, status = provider.get(request, provider.get_get_url())

    assert template == 'core/error.html'
    assert status == 200
    assert context['title'] == 'RADAR OAuth configuration error'
    assert 'different RDMO instance' in str(context['errors'][0])
    assert provider.get_from_session(request, 'state') is None
    assert provider.get_from_session(request, 'access_token') is None


@pytest.mark.parametrize('host', ['rdmo.example.test', 'rdmo.example.test:443', 'RDMO.EXAMPLE.TEST'])
@override_settings(ALLOWED_HOSTS=['rdmo.example.test'])
def test_oauth_authorization_accepts_same_origin(host):
    provider = make_provider(provider_class=RadarExportProvider)
    request = RequestFactory().get('/', secure=True, HTTP_HOST=host)
    request.session = {}

    response = provider.authorize(request)

    assert response.status_code == 302
    query = parse_qs(urlparse(response.url).query)
    assert query['state'] == [provider.get_from_session(request, 'state')]
    assert query['redirect_uri'] == [provider.redirect_uri]


def test_oauth_callback_exchanges_code_and_resumes_request(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.request.GET = {'state': 'expected-state', 'code': 'authorization-code'}
    provider.store_in_session(provider.request, 'state', 'expected-state')
    provider.store_in_session(provider.request, 'request', ('get', provider.get_get_url()))
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'access_token': 'oauth-token'}

    def post(url, data, **kwargs):
        captured['url'] = url
        captured['data'] = data
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr('rdmo.services.providers.requests.post', post)
    monkeypatch.setattr(provider, 'get', lambda request, url: ('resumed', url))

    result = provider.callback(provider.request)

    assert result == ('resumed', provider.get_get_url())
    assert captured['url'].startswith('https://radar.example.test/radar-backend/oauth/token?')
    assert captured['auth'] == ('configured-client-id', 'client-secret')
    assert provider.get_from_session(provider.request, 'access_token') == 'oauth-token'


@override_settings(RADAR_PROVIDER={
    'radar_url': 'https://radar.example.test',
    'client_id': 'configured-client-id',
    'client_secret': 'client-secret',
    'redirect_uri': 'https://rdmo.example.test/services/oauth/radar/callback/',
    'oauth_token_auth_method': 'client_secret_post',
})
def test_oauth_callback_uses_client_secret_post(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.request.GET = {'state': 'expected-state', 'code': 'authorization-code'}
    provider.store_in_session(provider.request, 'state', 'expected-state')
    provider.store_in_session(provider.request, 'request', ('get', provider.get_get_url()))
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'access_token': 'oauth-token'}

    def post(url, data, **kwargs):
        captured['url'] = url
        captured['data'] = data
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr('rdmo.services.providers.requests.post', post)
    monkeypatch.setattr(provider, 'get', lambda request, url: ('resumed', url))

    result = provider.callback(provider.request)

    assert result == ('resumed', provider.get_get_url())
    assert captured['url'].rstrip('?') == 'https://radar.example.test/radar-backend/oauth/token'
    assert 'authorization-code' not in captured['url']
    assert captured['data'] == {
        'grant_type': 'authorization_code',
        'redirect_uri': 'https://rdmo.example.test/services/oauth/radar/callback/',
        'code': 'authorization-code',
        'client_id': 'configured-client-id',
        'client_secret': 'client-secret'
    }
    assert captured['auth'] is None
    assert captured['headers'] == {'Accept': 'application/json'}


@override_settings(RADAR_PROVIDER={
    'radar_url': 'https://radar.example.test',
    'client_id': 'configured-client-id',
    'client_secret': 'client-secret',
    'redirect_uri': 'https://rdmo.example.test/services/oauth/radar/callback/',
    'oauth_token_auth_method': 'unsupported',
})
def test_oauth_token_auth_method_rejects_unsupported_value():
    provider = make_provider(provider_class=RadarExportProvider)

    with pytest.raises(ImproperlyConfigured):
        provider.get_callback_auth(provider.request)


@pytest.mark.parametrize('status', [400, 401])
def test_oauth_callback_renders_generic_failure(monkeypatch, caplog, status):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.store_in_session(provider.request, 'request', ('get', provider.get_get_url()))
    response = requests.Response()
    response.status_code = status
    response._content = b'private-token client-secret authorization-code'

    def callback(*args):
        raise requests.HTTPError('private exception text', response=response)

    monkeypatch.setattr(OauthProviderMixin, 'callback', callback)
    monkeypatch.setattr(
        'rdmo_radar.exports.providers.render',
        lambda request, template, context, status: (template, context, status),
    )
    template, context, response_status = provider.callback(provider.request)

    assert template == 'core/error.html'
    assert response_status == 200
    assert context['title'] == 'RADAR OAuth error'
    assert 'OAuth authorization could not be completed' in str(context['errors'][0])
    assert f'status={status}' in caplog.text
    for secret in ('private-token', 'client-secret', 'authorization-code', 'private exception text'):
        assert secret not in caplog.text
        assert secret not in str(context)


def test_oauth_callback_network_failure_during_export_warns_without_retry(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    prepare_oauth_creation(provider)
    calls = []

    def callback(*args):
        calls.append(args)
        raise requests.Timeout('private timeout details')

    monkeypatch.setattr(OauthProviderMixin, 'callback', callback)
    monkeypatch.setattr('rdmo_radar.exports.providers.render', lambda request, template, context, status: context)
    context = provider.callback(provider.request)

    assert len(calls) == 1
    assert 'OAuth authorization could not be completed' in str(context['errors'][0])
    assert 'existing draft' in str(context['errors'][0])
    assert 'private timeout details' not in str(context)


@pytest.mark.parametrize(('status', 'expected'), [
    (400, 'rejected the dataset metadata'), (422, 'rejected the dataset metadata'),
    (403, 'does not have permission'), (500, 'existing draft'),
])
def test_oauth_error_hook_uses_saved_operation_and_safe_message(status, expected):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.store_in_session(provider.request, 'operation', 'create_dataset')
    response = SimpleNamespace(status_code=status, json=lambda: {'exception': 'private-token'})
    message = str(provider.get_error_message(response))
    assert expected in message
    assert 'private-token' not in message


@pytest.mark.parametrize('provider_class', [RadarCredentialsExportProvider, RadarExportProvider])
def test_export_validation_message_is_kept_in_user_error(provider_class, caplog):
    provider = make_provider(provider_class=provider_class)
    detail = 'Es existiert bereits ein Eintrag mit dem gleichen Namen auf dieser Ebene.'
    error = http_error(422)
    error.response._content = json.dumps({'exception': f'Validation exception: {detail}'}).encode()
    if provider_class is RadarExportProvider:
        provider.store_in_session(provider.request, 'operation', 'create_dataset')
        message = provider.get_error_message(error.response)
    else:
        message = provider.get_client_error_message(error, stage='export')
    assert str(message) == f'RADAR rejected the dataset metadata: {detail}'
    assert detail not in caplog.text


@pytest.mark.parametrize(('status', 'stage', 'expected'), [
    (400, 'request', 'could not process the request'),
    (404, 'request', 'resource or API endpoint could not be found'),
    (404, 'export', 'resource or API endpoint could not be found'),
    (500, 'request', 'reported a server error'),
    (502, 'export', 'reported a server error'),
    (503, 'export', 'reported a server error'),
    (504, 'export', 'reported a server error'),
    (418, 'request', 'could not complete the request'),
])
def test_request_errors_explain_status_without_exposing_response_body(status, stage, expected, caplog):
    provider = make_provider()
    error = http_error(status)
    error.response._content = b'{"exception": "Private server details"}'
    message = str(provider.get_client_error_message(error, stage=stage))
    assert expected in message
    if stage == 'export' and status >= 500:
        assert 'Check RADAR for an existing draft before retrying' in message
    assert 'Private server details' not in message
    assert 'Private server details' not in caplog.text


@pytest.mark.parametrize('body', [
    b'not JSON', b'[]', b'{}', b'{"exception": null}', b'{"exception": 123}',
    b'{"exception": "Validation exception: "}',
    b'{"exception": "Authentication exception: private-token"}',
])
def test_export_validation_error_without_usable_detail_keeps_generic_message(body, caplog):
    provider = make_provider()
    error = http_error(422)
    error.response._content = body
    message = str(provider.get_client_error_message(error, stage='export'))
    assert message == (
        'RADAR rejected the dataset metadata. Review the metadata and mapping warnings before retrying.'
    )
    assert 'private-token' not in caplog.text


@pytest.mark.parametrize(('status', 'stage'), [
    (400, 'export'), (401, 'export'), (500, 'export'),
    (422, 'request'), (422, 'login'), (422, 'oauth'),
])
def test_validation_details_are_only_shown_for_rejected_dataset_exports(status, stage, caplog):
    provider = make_provider()
    error = http_error(status)
    error.response._content = b'{"exception": "Validation exception: unexpected detail"}'
    assert 'unexpected detail' not in str(provider.get_client_error_message(error, stage=stage))
    assert 'unexpected detail' not in caplog.text


def test_oauth_success_callback_handles_malformed_response(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    monkeypatch.setattr('rdmo_radar.exports.providers.render',
                        lambda request, template, context, status: context)
    response = SimpleNamespace(json=lambda: ['invalid'])
    assert 'existing draft' in str(provider.post_success(provider.request, response)['errors'][0])
    assert 'try again later' in str(provider.get_success(provider.request, response)['errors'][0])


@pytest.mark.parametrize(('field', 'value'), [
    (None, None), (None, {}), ('provider', 'another.Provider'), ('project_id', None),
    ('project_id', True), ('persist', 1), ('radar_url', None), ('language', None),
    ('dataset', {'key': 'project'}),
    ('dataset', {'key': 'project', 'label': 'Project', 'scope': {'coordinate': {1, 10}}}),
])
def test_oauth_incomplete_context_blocks_replay_and_retains_confirmed_id(monkeypatch, field, value):
    provider = make_provider(provider_class=RadarExportProvider)
    context = prepare_oauth_creation(provider)
    if field is None:
        provider.store_in_session(provider.request, 'export_context', value)
    else:
        context[field] = value
    provider.get_service = Mock(side_effect=AssertionError('Reader rebuilt'))
    writer = Mock()
    provider.mapping = replace(provider.mapping, store_result=writer)
    http = Mock(side_effect=AssertionError('Incomplete export submitted'))
    monkeypatch.setattr('rdmo.services.providers.requests.post', http)
    monkeypatch.setattr('rdmo_radar.exports.providers.render',
                        lambda request, template, context, status=200: context)

    result = provider.callback(provider.request)

    assert 'incomplete or was canceled' in str(result['errors'][0])
    http.assert_not_called()
    writer.assert_not_called()
    provider.get_service.assert_not_called()
    for key in ('request', 'state', 'operation', 'export_context'):
        assert provider.get_from_session(provider.request, key) is None
    # A confirmed ID must still be recoverable if a result reaches this hook
    # without any destination context. Never construct a link from new settings.
    result = provider.post_success(provider.request, SimpleNamespace(json=lambda: {'id': 'confirmed'}))
    assert result == {'radar_id': 'confirmed', 'radar_url': None}
    writer.assert_not_called()


@pytest.mark.parametrize('pending', [
    None, {}, [], ['post'], ['delete', 'https://radar.test'],
    ['get', None], ['post', 'https://radar.test', [], None, None],
    ['post', 'https://radar.test', {}, 'unexpected files', None],
])
def test_oauth_malformed_pending_request_is_not_replayed(monkeypatch, pending):
    provider = make_provider(provider_class=RadarExportProvider)
    prepare_oauth_creation(provider)
    provider.store_in_session(provider.request, 'request', pending)
    http = Mock(side_effect=AssertionError('Malformed request submitted'))
    monkeypatch.setattr('rdmo.services.providers.requests.post', http)
    monkeypatch.setattr('rdmo_radar.exports.providers.render',
                        lambda request, template, context, status: context)
    result = provider.callback(provider.request)
    assert 'incomplete or was canceled' in str(result['errors'][0])
    http.assert_not_called()


def test_oauth_cancel_clears_pending_work_before_preparation_and_keeps_token(monkeypatch):
    provider = make_provider(post={'cancel': '1'}, provider_class=RadarExportProvider)
    prepare_oauth_creation(provider)
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    provider.get_export_form = Mock(side_effect=AssertionError('Form prepared during cancellation'))
    monkeypatch.setattr('rdmo_radar.exports.providers.redirect', lambda *args: args)

    assert provider.submit() == ('project', provider.project.pk)
    assert provider.get_from_session(provider.request, 'access_token') == 'bearer-token'
    for key in ('request', 'state', 'operation', 'export_context'):
        assert provider.get_from_session(provider.request, key) is None
    provider.get_export_form.assert_not_called()


def test_oauth_active_post_preserves_captured_destination_and_releases_it(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    context = prepare_oauth_creation(provider)
    context['persist'] = True
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    pending = provider.get_from_session(provider.request, 'request')
    writer = Mock()
    provider.mapping = replace(provider.mapping, store_result=writer)
    provider.render_export_result = Mock(return_value='confirmed result')
    monkeypatch.setattr('rdmo_radar.exports.providers.Project.objects.get', lambda **kwargs: provider.project)

    def post(url, **kwargs):
        assert url == pending[1]
        assert kwargs['json'] is pending[2]
        # Also mutate the former scope to verify the active destination is an
        # independent snapshot, rather than another reference to session data.
        context['dataset']['scope']['set_index'] = 99
        context['radar_url'] = 'https://another-radar.test'
        context['language'] = 'en'
        provider.pop_from_session(provider.request, 'export_context')
        result = requests.Response()
        result.status_code = 201
        result._content = b'{"id": "confirmed"}'
        return result

    http = Mock(side_effect=post)
    monkeypatch.setattr('rdmo.services.providers.requests.post', http)
    assert provider.post(provider.request, *pending[1:]) == 'confirmed result'
    http.assert_called_once()
    dataset = ExportDataset('dataset:10|3', 'Dataset', {'set_prefix': '10', 'set_index': 3})
    writer.assert_called_once_with(
        provider.project, dataset, 'confirmed', 'https://radar.example.test/radar/de/dataset/confirmed',
    )
    assert provider._active_export == (None, None)
    # A later confirmation cannot reuse the destination of an earlier POST.
    provider.render_export_result.reset_mock()
    provider.post_success(provider.request, SimpleNamespace(json=lambda: {'id': 'later'}))
    provider.render_export_result.assert_called_once_with(provider.request, 'later', None, stored=False)
    writer.assert_called_once()


def test_oauth_workspace_callback_stores_locally_sorted_choices(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.store_in_session(provider.request, 'project_id', 1)
    monkeypatch.setattr('rdmo_radar.exports.providers.redirect', lambda *args: args)
    response = SimpleNamespace(json=lambda: {'data': [
        {'id': 'z', 'descriptiveMetadata': {'title': 'zebra'}},
        {'id': 'a1', 'descriptiveMetadata': {'title': 'Alpha'}},
        {'id': 'b', 'descriptiveMetadata': {'title': 'Beta'}},
        {'id': 'a2', 'descriptiveMetadata': {'title': 'alpha'}},
    ]})

    assert provider.get_success(provider.request, response) == ('project_export', 1, 'radar')
    assert provider.get_from_session(provider.request, 'workspace_choices') == [
        ('a1', 'Alpha'), ('a2', 'alpha'), ('b', 'Beta'), ('z', 'zebra'),
    ]
    assert provider.get_from_session(provider.request, 'get') is True


def test_credentials_provider_uses_json_api_and_registered_url():
    provider = make_provider()

    assert provider.client.token_url == 'https://radar.example.test/radar/api/tokens'
    assert provider.client_id == 'configured-client-id'
    assert provider.redirect_url == 'https://rdmo.example.test/'


@override_settings(RADAR_PROVIDER={
    'radar_url': 'https://radar.example.test',
    'client_id': 'configured-client-id',
    'client_secret': 'client-secret',
    'redirect_uri': 'https://rdmo.example.test:8443/services/oauth/radar/callback/?source=test#fragment',
})
def test_credentials_redirect_url_preserves_origin_only():
    provider = make_provider()

    assert provider.redirect_url == 'https://rdmo.example.test:8443/'


def fake_client(monkeypatch, **methods):
    client = SimpleNamespace(radar_url='https://radar.example.test', **methods)
    monkeypatch.setattr('rdmo_radar.exports.credentials.RadarClient', lambda *args: client)
    return client


def test_credentials_are_exchanged_without_being_stored(monkeypatch):
    provider = make_provider({'stage': 'credentials', 'username': 'radar-user', 'password': 'radar-password'})
    captured = []

    def authenticate(username, password):
        captured.append((username, password))
        return 'bearer-token'

    fake_client(monkeypatch, authenticate=authenticate)
    monkeypatch.setattr('rdmo_radar.exports.credentials.redirect', lambda *args: args)
    assert provider.submit_credentials_form() == ('project_export', 1, 'radar')
    assert captured == [('radar-user', 'radar-password')]
    assert provider.request.session == {
        'rdmo_radar.exports.RadarCredentialsExportProvider.access_token': 'bearer-token',
    }
    assert 'radar-password' not in repr(provider.request.session)


@pytest.mark.parametrize('status', [400, 401])
def test_failed_login_does_not_store_credentials(monkeypatch, caplog, status):
    provider = make_provider({'stage': 'credentials', 'username': 'radar-user', 'password': 'wrong-password'})

    def authenticate(*args):
        raise http_error(status)

    fake_client(monkeypatch, authenticate=authenticate)
    monkeypatch.setattr(provider, 'render_credentials_form', lambda form: form)
    form = provider.submit_credentials_form()
    assert not form.is_valid()
    assert form.non_field_errors()
    assert 'log in again' in str(form.non_field_errors())
    assert 'Private upstream error' not in str(form.non_field_errors())
    assert 'Private upstream error' not in caplog.text
    assert provider.request.session == {}


def test_workspace_request_uses_client_token(monkeypatch):
    provider = make_provider()
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    provider.store_in_session(provider.request, 'dataset_choices', [(0, 'Dataset')])
    provider.store_in_session(provider.request, 'radar_urls', [None])
    captured = []

    def get_workspaces(token):
        captured.append(token)
        return [('workspace-1', 'Workspace')]

    fake_client(monkeypatch, get_workspaces=get_workspaces)
    monkeypatch.setattr('rdmo_radar.exports.credentials.render', lambda request, template, context, status: context)
    context = provider.render_export_form()
    assert captured == ['bearer-token']
    assert context['form'].fields['workspace'].widget.choices == [('workspace-1', 'Workspace')]


def test_workspace_authentication_failure_drops_token_and_preserves_choices(monkeypatch):
    provider = make_provider()
    provider.store_in_session(provider.request, 'access_token', 'expired-token')
    provider.store_in_session(provider.request, 'dataset_choices', [(0, 'Dataset')])
    provider.store_in_session(provider.request, 'radar_urls', [None])
    provider.store_in_session(provider.request, 'project_id', 1)

    def get_workspaces(token):
        raise http_error(401)

    fake_client(monkeypatch, get_workspaces=get_workspaces)
    monkeypatch.setattr(provider, 'render_credentials_form', lambda form=None, error=None: error)
    assert 'log in again' in str(provider.render_export_form())
    assert provider.get_from_session(provider.request, 'access_token') is None
    assert provider.get_from_session(provider.request, 'dataset_choices') == [(0, 'Dataset')]


@pytest.mark.parametrize('error', [
    http_error(403), requests.ConnectionError('Private connection error'), RadarProtocolError(),
])
def test_workspace_non_authentication_failure_preserves_token(monkeypatch, error):
    provider = make_provider()
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')

    def get_workspaces(token):
        raise error

    fake_client(monkeypatch, get_workspaces=get_workspaces)
    monkeypatch.setattr('rdmo_radar.exports.credentials.render', lambda request, template, context, status: context)
    context = provider.render_export_form()
    assert context['error']
    assert provider.get_from_session(provider.request, 'access_token') == 'bearer-token'


def test_no_workspaces_is_reported_without_discarding_token(monkeypatch):
    provider = make_provider()
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    fake_client(monkeypatch, get_workspaces=lambda token: [])
    monkeypatch.setattr('rdmo_radar.exports.credentials.render', lambda request, template, context, status: context)
    context = provider.render_export_form()
    assert 'No RADAR workspaces' in str(context['error'])
    assert not context['form'].fields['workspace'].choices
    assert provider.get_from_session(provider.request, 'access_token') == 'bearer-token'


def test_cancel_clears_export_session(monkeypatch):
    provider = make_provider({'cancel': '1'})
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    provider.store_in_session(provider.request, 'dataset_choices', [(0, 'Dataset')])
    provider.store_in_session(provider.request, 'project_id', 1)
    monkeypatch.setattr('rdmo_radar.exports.credentials.redirect', lambda *args: args)

    result = provider.submit()

    assert result == ('project', 1)
    assert provider.request.session == {}


def export_provider(provider_class=RadarCredentialsExportProvider):
    provider = make_provider({'stage': 'export', 'dataset': '0', 'workspace': 'workspace-1'}, provider_class)
    for key, value in (
        ('access_token', 'bearer-token'), ('dataset_choices', [(0, 'Dataset')]),
        ('workspace_choices', [('workspace-1', 'Workspace')]), ('radar_urls', [None]), ('project_id', 1),
    ):
        provider.store_in_session(provider.request, key, value)
    provider.get_datasets = lambda: [ExportDataset('0', 'Dataset', {'set_prefix': '', 'set_index': 0})]
    provider.get_service().mapping = lambda context: MappingResult(RadarMetadata(title='Dataset'))
    return provider


@pytest.mark.parametrize('provider_class', [RadarCredentialsExportProvider, RadarExportProvider])
@pytest.mark.parametrize('payload', [
    {},
    {
        'technicalMetadata': {'retentionPeriod': 3, 'archiveDate': 0, 'responsibleEmail': 'other@example.test'},
        'descriptiveMetadata': {'title': '', 'language': 'custom-language', 'keywords': {'keyword': []}},
        'customField': {'enabled': False, 'values': [0, None]},
    },
])
def test_payload_override_is_sent_unchanged_without_canonical_mapping(monkeypatch, provider_class, payload):
    calls = []

    class ExampleRadarExportProvider(provider_class):
        def get_payload(self, dataset):
            calls.append(dataset)
            return payload

    provider = export_provider(ExampleRadarExportProvider)
    service = provider.get_service()
    service.mapping = Mock(side_effect=AssertionError('Canonical mapping called'))
    service.serializer = Mock(side_effect=AssertionError('Canonical serializer called'))
    service.writer = Mock()
    original = deepcopy(payload)
    captured = []

    def create_dataset(token, workspace, body):
        captured.append(body)
        assert (token, workspace) == ('bearer-token', 'workspace-1')
        return {'id': 'confirmed'}

    def post(request, url, body):
        captured.append(body)
        assert url == 'https://radar.example.test/radar/api/workspaces/workspace-1/datasets'
        return 'sent'

    fake_client(monkeypatch, create_dataset=create_dataset)
    monkeypatch.setattr(provider, 'post', post, raising=False)
    monkeypatch.setattr(provider, 'render_export_result', lambda *args, **kwargs: 'sent')

    assert provider.get_export_form().mapping_warnings == []
    assert calls == []
    assert provider.submit() == 'sent'
    assert [dataset.key for dataset in calls] == ['0']
    assert len(captured) == 1
    assert captured[0] is payload
    assert payload == original
    service.mapping.assert_not_called()
    service.serializer.assert_not_called()
    if issubclass(provider_class, RadarCredentialsExportProvider):
        service.writer.assert_called_once_with(calls[0], 'confirmed',
                                               'https://radar.example.test/radar/en/dataset/confirmed')
    else:
        service.writer.assert_not_called()


@pytest.mark.parametrize('provider_class', [RadarCredentialsExportProvider, RadarExportProvider])
@pytest.mark.parametrize(('result', 'error_type'), [
    (None, 'TypeError'), ([], 'TypeError'), ({'value': object()}, 'TypeError'),
    ({'value': float('nan')}, 'ValueError'), (RuntimeError('Private payload details'), 'RuntimeError'),
])
def test_payload_preparation_failure_preserves_form_without_submission(
    monkeypatch, caplog, provider_class, result, error_type,
):
    class ExampleRadarExportProvider(provider_class):
        def get_payload(self, dataset):
            if isinstance(result, Exception):
                raise result
            return result

    provider = export_provider(ExampleRadarExportProvider)
    provider.get_service().writer = Mock()
    no_submission = Mock(side_effect=AssertionError('Invalid payload submitted'))
    fake_client(monkeypatch, create_dataset=no_submission)
    monkeypatch.setattr(provider, 'post', no_submission, raising=False)
    for module in ('credentials', 'providers'):
        monkeypatch.setattr(f'rdmo_radar.exports.{module}.render',
                            lambda request, template, context, status: context)

    form = provider.submit()['form']

    assert form.is_bound
    assert form.cleaned_data['dataset'] == '0'
    assert form.cleaned_data['workspace'] == 'workspace-1'
    assert 'could not be prepared' in str(form.non_field_errors())
    assert 'Private payload details' not in str(form.errors)
    assert 'Private payload details' not in caplog.text
    assert f'provider={provider.class_name} error_type={error_type}' in caplog.text
    assert provider.get_from_session(provider.request, 'access_token') == 'bearer-token'
    assert provider.get_from_session(provider.request, 'export_context') is None
    assert provider.get_from_session(provider.request, 'operation') is None
    no_submission.assert_not_called()
    provider.get_service().writer.assert_not_called()


@pytest.mark.parametrize('provider_class', [RadarCredentialsExportProvider, RadarExportProvider])
@pytest.mark.parametrize('selection', ['invalid_workspace', 'stale_project', 'removed_dataset'])
def test_payload_hook_is_not_called_for_invalid_selections(monkeypatch, provider_class, selection):
    class ExampleRadarExportProvider(provider_class):
        def get_payload(self, dataset):
            pytest.fail('Payload hook called for an invalid selection')

    provider = export_provider(ExampleRadarExportProvider)
    if selection == 'invalid_workspace':
        provider.request.POST['workspace'] = 'unlisted'
    elif selection == 'stale_project':
        provider.store_in_session(provider.request, 'project_id', 2)
    else:
        provider.get_datasets = lambda: []
    for module in ('credentials', 'providers'):
        monkeypatch.setattr(f'rdmo_radar.exports.{module}.render',
                            lambda request, template, context, status: context)
    assert provider.submit()['form'].errors


@pytest.mark.parametrize('overridden', [False, True])
@pytest.mark.parametrize('show_warnings', [None, True, False])
def test_mapping_warnings_follow_payload_hook_and_explicit_setting(overridden, show_warnings):
    class ExampleRadarExportProvider(RadarExportProvider):
        show_mapping_warnings = show_warnings

    if overridden:
        ExampleRadarExportProvider.get_payload = Mock(side_effect=AssertionError('Payload hook called for warnings'))
    provider = export_provider(ExampleRadarExportProvider)
    service = provider.get_service()
    service.mapping = Mock(return_value=MappingResult(RadarMetadata(title='Dataset')))

    warnings = provider.get_mapping_warnings()

    enabled = show_warnings if show_warnings is not None else not overridden
    assert bool(warnings) == enabled
    assert service.mapping.call_count == int(enabled)
    if overridden:
        ExampleRadarExportProvider.get_payload.assert_not_called()


def test_custom_mapping_warnings_remain_independently_overridable():
    class ExampleRadarExportProvider(RadarExportProvider):
        def get_payload(self, dataset):
            pytest.fail('Payload hook called for warnings')

        def get_mapping_warnings(self):
            return [{'title': 'Custom request', 'missing': ['Custom requirement'], 'issues': ()}]

    provider = export_provider(ExampleRadarExportProvider)
    assert provider.get_export_form().mapping_warnings == [{
        'title': 'Custom request', 'missing': ['Custom requirement'], 'issues': (),
    }]


def test_dataset_export_clears_bearer_token(monkeypatch):
    provider = export_provider()
    captured = []

    def create_dataset(token, workspace, payload):
        captured.append((token, workspace, payload))
        return {'id': 'radar-1'}

    fake_client(monkeypatch, create_dataset=create_dataset)
    monkeypatch.setattr(
        provider, 'render_export_result', lambda request, radar_id, url, **kwargs: ('success', radar_id),
    )
    assert provider.submit_export_form() == ('success', 'radar-1')
    assert len(captured) == 1
    assert captured[0][:2] == ('bearer-token', 'workspace-1')
    assert captured[0][2]['descriptiveMetadata'] == {'title': 'Dataset'}
    assert provider.request.session == {}


@pytest.mark.parametrize('raw_payload', [False, True])
@pytest.mark.parametrize(('error', 'expected'), [
    (http_error(403), 'does not have permission'),
    (http_error(400), 'rejected the dataset metadata'),
    (http_error(422), 'rejected the dataset metadata'),
    (http_error(500), 'existing draft'),
    (requests.Timeout('Private timeout error'), 'existing draft'),
    (RadarProtocolError(), 'existing draft'),
])
def test_dataset_failure_keeps_bound_form_and_token(monkeypatch, caplog, error, expected, raw_payload):
    provider = export_provider()
    calls = []
    payload = {'technicalMetadata': {}, 'descriptiveMetadata': {'title': 'Custom request'}}
    if raw_payload:
        monkeypatch.setattr(RadarCredentialsExportProvider, 'get_payload', lambda self, dataset: payload)

    def create_dataset(*args):
        calls.append(args)
        raise error

    fake_client(monkeypatch, create_dataset=create_dataset)
    monkeypatch.setattr('rdmo_radar.exports.credentials.render', lambda request, template, context, status: context)
    context = provider.submit_export_form()
    assert len(calls) == 1
    if raw_payload:
        assert calls[0][2] is payload
    assert context['form'].is_bound
    assert context['form'].cleaned_data['dataset'] == '0'
    assert context['form'].cleaned_data['workspace'] == 'workspace-1'
    assert provider.get_from_session(provider.request, 'access_token') == 'bearer-token'
    assert 'log in' not in str(context['error'])
    assert expected in str(context['error'])
    assert 'Private' not in str(context['error'])
    assert 'Private' not in caplog.text


def test_dataset_authentication_failure_returns_to_credentials(monkeypatch):
    provider = export_provider()

    def create_dataset(*args):
        raise http_error(401)

    fake_client(monkeypatch, create_dataset=create_dataset)
    monkeypatch.setattr(provider, 'render_credentials_form', lambda error: error)
    assert 'log in again' in str(provider.submit_export_form())
    assert provider.get_from_session(provider.request, 'access_token') is None
    assert provider.get_from_session(provider.request, 'dataset_choices') == [(0, 'Dataset')]


def test_invalid_export_form_does_not_call_client(monkeypatch):
    provider = export_provider()
    provider.request.POST['workspace'] = 'unlisted'
    fake_client(monkeypatch, create_dataset=lambda *args: pytest.fail('Client called for invalid choices'))
    monkeypatch.setattr(provider, 'render_export_form', lambda form: form)
    assert not provider.submit_export_form().is_valid()


@pytest.mark.parametrize('provider_class', [RadarCredentialsExportProvider, RadarExportProvider])
def test_direct_export_uses_rddm_9_3_and_millisecond_timestamps(monkeypatch, provider_class):
    provider = make_provider(provider_class=provider_class)
    provider.get_service().clock = lambda: 1_725_000_000.123
    provider.get_service().mapping = lambda context: MappingResult(RadarMetadata(title='Draft dataset'))

    payload = provider.get_payload(ExportDataset('0', 'Dataset', {'set_prefix': '', 'set_index': 0}))

    assert payload['technicalMetadata']['schema'] == {'key': 'RDDM', 'version': '9.3'}
    assert payload['technicalMetadata']['archiveDate'] == 1_725_000_000_123
    assert payload['technicalMetadata']['publishDate'] == 1_725_000_000_123
    assert payload['technicalMetadata']['responsibleEmail'] == provider.request.user.email
    assert payload['descriptiveMetadata'] == {'title': 'Draft dataset'}


def test_direct_draft_omits_unavailable_descriptive_metadata():
    provider = make_provider()
    provider.get_service().mapping = lambda context: MappingResult(RadarMetadata())
    assert dataset_payload(provider, 0) == {'title': 'Dataset #1'}


def test_provider_form_validates_choices_and_escapes_export_link():
    form = RadarExportProvider.Form(
        dataset_choices=[('0', '<script>alert(1)</script>')],
        workspace_choices=[('workspace-1', 'Workspace')],
        radar_urls=['https://radar.example.test/dataset/?q="<script>'],
    )

    field_html = str(form['dataset'])
    assert '<script>' not in field_html
    assert '&lt;script&gt;' in field_html
    assert 'rel="noopener noreferrer"' in field_html

    invalid_form = RadarExportProvider.Form(
        data={'dataset': 'not-displayed', 'workspace': 'not-displayed'},
        dataset_choices=[('0', 'Dataset')],
        workspace_choices=[('workspace-1', 'Workspace')],
        radar_urls=[None],
    )
    assert not invalid_form.is_valid()


def test_dataset_resource_type_does_not_use_file_format(db):
    export = make_export({'project/dataset/description': 'Resource', 'project/dataset/format': 'text/csv'})
    assert dataset_payload(export, 0)['resource'] == {'value': 'Resource', 'resourceType': None}
    assert read_metadata(export, 0).issues == ()
    assert XMLVocabulary.data_source_options['radar_data_source/trial'] == 'Trial'
    assert XMLVocabulary.resource_type_general_options['resource_type_general/computational_notebook'] == \
        'ComputationalNotebook'
    assert XMLVocabulary.description_type_options['description_type/version_notes'] == 'VersionNotes'
    assert XMLVocabulary.contributor_type_options['contributor_type/translator'] == 'Translator'
    assert XMLVocabulary.related_identifier_type_options['identifier_type/raid'] == 'RAiD'
    assert XMLVocabulary.related_identifier_type_options['identifier_type/swhid'] == 'SWHID'
    assert XMLVocabulary.relation_type_options['relation_type/is_translation_of'] == 'IsTranslationOf'


def test_api_and_xml_mappings_are_kept_separate():
    assert XMLVocabulary.language_options['language/en'] == 'eng'
    assert APIVocabulary.language_options['language/en'] == 'ENG'
    assert XMLVocabulary.resource_type_general_options['resource_type_general/dataset'] == 'Dataset'
    assert APIVocabulary.resource_type_general_options['resource_type_general/dataset'] == 'DATASET'
    assert XMLVocabulary.funder_identifier_scheme_options['name_identifier_scheme/insi'] == 'ISNI'
    assert XMLVocabulary.name_identifier_scheme_options['name_identifier_scheme/insi'] == 'Other'


def test_compute_metadata_keeps_primary_structured_name(db):
    export = make_export()
    for part, value in [('name', 'Doe, Jane'), ('given_name', 'Jane'), ('family_name', 'Doe')]:
        add_answer(export.project, f'project/dataset/creator/{part}', value, set_prefix='0')
    name = read_metadata(export, 0).metadata.creators[0]
    assert name.name == 'Doe, Jane'
    assert name.given_name == 'Jane'
    assert name.family_name == 'Doe'


def test_renderer_preserves_structured_names_and_contributor_type(capsys):
    xml = RadarExportRenderer().render({
        'creators': {'creator': [{
            'creatorName': 'Doe, Jane',
            'givenName': 'Jane',
            'familyName': 'Doe',
        }]},
        'contributors': {'contributor': [{
            'contributorName': 'Smith, John',
            'givenName': 'John',
            'familyName': 'Smith',
            'contributorType': 'DataManager',
        }]},
    })
    root = ElementTree.fromstring(xml)
    namespace = {'radar': 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'}

    assert root.findtext('.//radar:creatorName', namespaces=namespace) == 'Doe, Jane'
    contributor = root.find('.//radar:contributor', namespace)
    assert contributor.attrib['contributorType'] == 'DataManager'
    assert contributor.findtext('radar:contributorName', namespaces=namespace) == 'Smith, John'
    assert capsys.readouterr().out == ''


def test_zip_export_is_complete_and_readable():
    export = configure_service(RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport'))
    export.project = SimpleNamespace(title='Project')
    export.get_datasets = lambda: [0, 1]
    export.get_service().mapping = lambda context: MappingResult(
        complete_metadata(title=f'Dataset {context.set_index + 1}'),
    )

    response = export.render()
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['Dataset 1.xml', 'Dataset 2.xml']
        assert b'<re:title>Dataset 1</re:title>' in archive.read('Dataset 1.xml')
        for file_name in archive.namelist():
            assert validate_radar_xml(archive.read(file_name)) is None


def test_renderer_output_validates_against_rddm_9_3_schema():
    xml = RadarExportRenderer().render(make_valid_xml_dataset(
        alternateIdentifiers={
            'alternateIdentifier': [{'value': 'local-id', 'alternateIdentifierType': 'Local'}]
        },
        relatedIdentifiers={
            'relatedIdentifier': [{
                'value': 'https://example.test/software',
                'relatedIdentifierType': 'SWHID',
                'relationType': 'IsCollectedBy'
            }]
        },
        contributors={'contributor': [{
            'contributorName': 'Smith, John',
            'contributorType': 'Translator'
        }]},
        descriptions={'description': [{'value': 'Version changes', 'descriptionType': 'VersionNotes'}]},
        fundingReferences={'fundingReference': [{
            'funderName': 'Example Funder',
            'funderIdentifier': {'value': 'https://ror.org/123', 'type': 'ROR'}
        }]}
    ))

    assert get_radar_schema().version == '9.3'
    assert validate_radar_xml(xml) is None

    root = ElementTree.fromstring(xml)
    element_namespace = '{http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements}'
    assert [element.tag for element in root] == [
        f'{element_namespace}identifier',
        f'{element_namespace}alternateIdentifiers',
        f'{element_namespace}relatedIdentifiers',
        f'{element_namespace}creators',
        f'{element_namespace}contributors',
        f'{element_namespace}title',
        f'{element_namespace}descriptions',
        f'{element_namespace}publishers',
        f'{element_namespace}productionYear',
        f'{element_namespace}language',
        f'{element_namespace}subjectAreas',
        f'{element_namespace}resource',
        f'{element_namespace}rights',
        f'{element_namespace}rightsHolders',
        f'{element_namespace}fundingReferences',
        f'{element_namespace}version'
    ]


def test_invalid_xml_export_shows_warnings_before_download(monkeypatch):
    export = configure_service(RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport'))
    export.project = SimpleNamespace(pk=1, title='Project', get_absolute_url=lambda: '/projects/1/')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/')
    export.get_datasets = lambda: [0, 1]
    export.get_service().mapping = lambda context: MappingResult(
        complete_metadata() if context.set_index == 0 else RadarMetadata(title='Incomplete dataset'),
    )
    monkeypatch.setattr(
        'rdmo_radar.exports.exports.render',
        lambda request, template, context: SimpleNamespace(
            status_code=200,
            template=template,
            context=context,
        ),
    )

    response = export.render()

    assert response.status_code == 200
    assert response.template == 'plugins/exports_radar_xml_validation.html'
    assert response.context['project_url'] == '/projects/1/'
    assert [file['file_name'] for file in response.context['files']] == ['Dataset.xml', 'Incomplete dataset.xml']
    assert not response.context['files'][0]['has_warnings']
    assert response.context['files'][1]['has_warnings']
    missing = {field['path'] for field in response.context['files'][1]['missing_fields']}
    assert missing >= {'identifier', 'creators.creator'}


def test_invalid_xml_export_can_be_downloaded_after_confirmation():
    export = configure_service(RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport'))
    export.project = SimpleNamespace(pk=1, title='Project', get_absolute_url=lambda: '/projects/1/')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/', {'download': '1'})
    export.get_datasets = lambda: [0]
    export.get_service().mapping = lambda context: MappingResult(RadarMetadata(title='Incomplete dataset'))

    response = export.render()

    assert response.status_code == 200
    assert response['Content-Type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['Incomplete dataset.xml']
        xml_data = archive.read('Incomplete dataset.xml')
        assert b'<re:title>Incomplete dataset</re:title>' in xml_data
        assert validate_radar_xml(xml_data) is not None


def test_legacy_dataset_id_marker_reports_missing_required_metadata(monkeypatch):
    export = configure_service(RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport'))
    export.project = SimpleNamespace(pk=1, title='Project', get_absolute_url=lambda: '/projects/1/')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/')
    export.get_datasets = lambda: [0]
    export.get_service().mapping = lambda context: MappingResult(RadarMetadata())
    monkeypatch.setattr(
        'rdmo_radar.exports.exports.render',
        lambda request, template, context: SimpleNamespace(status_code=200, context=context),
    )

    response = export.render()

    assert response.status_code == 200
    missing = response.context['files'][0]['missing_fields']
    assert ('Identifier type', 'identifier.identifierType') in {
        (str(field['label']), field['path']) for field in missing
    }
    assert any(field['path'] == 'title' for field in missing)


def test_validation_returns_all_unique_schema_errors(monkeypatch):
    errors_from_schema = [
        SimpleNamespace(reason='First problem'),
        SimpleNamespace(reason='Second problem'),
        SimpleNamespace(reason='First problem'),
    ]
    schema = SimpleNamespace(iter_errors=lambda xml_data: errors_from_schema)
    monkeypatch.setattr('rdmo_radar.exports.validation.get_radar_schema', lambda: schema)

    errors = get_radar_validation_errors(b'<xml/>')

    assert errors == ('First problem', 'Second problem')
    assert validate_radar_xml(b'<xml/>') == 'First problem'


def test_xml_generation_failure_still_blocks_export(caplog):
    export = configure_service(RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport'))
    export.project = SimpleNamespace(pk=1, title='Project')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/', {'download': '1'})
    export.get_datasets = lambda: [0]
    export.get_service().mapping = lambda context: (_ for _ in ()).throw(ValueError('internal details'))

    response = export.render()

    assert response.status_code == 400
    assert response['Content-Type'].startswith('text/plain')
    assert response.content == b'RADAR XML export could not generate "1.xml".'
    assert b'internal details' not in response.content
    assert 'internal details' in caplog.text
