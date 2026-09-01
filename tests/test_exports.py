import io
import zipfile
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

import requests

from rdmo.services.providers import OauthProviderMixin

from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExportProvider
from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.exports.renderers import RadarExportRenderer


def make_provider(post=None, provider_class=RadarCredentialsExportProvider):
    class_name = f'rdmo_radar.exports.{provider_class.__name__}'
    provider = provider_class('radar', 'RADAR', class_name)
    provider.request = SimpleNamespace(
        POST=post or {},
        GET={},
        session={},
        user=SimpleNamespace(email='user@example.test'),
        LANGUAGE_CODE='en'
    )
    provider.project = SimpleNamespace(id=1)
    return provider


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


def test_oauth_render_redirects_and_preserves_workspace_request():
    provider = make_provider(provider_class=RadarExportProvider)
    provider.get_set = lambda *args, **kwargs: [SimpleNamespace(set_index=0, value='Dataset')]
    provider.get_text = lambda *args, **kwargs: None

    response = provider.render()

    query = parse_qs(urlparse(response.url).query)
    assert response.status_code == 302
    assert query['client_id'] == ['configured-client-id']
    assert query['redirect_uri'] == ['https://rdmo.example.test/services/oauth/radar/callback/']
    assert provider.get_from_session(provider.request, 'request') == ('get', provider.get_get_url())
    assert provider.get_from_session(provider.request, 'state') == query['state'][0]


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


def test_oauth_callback_renders_invalid_client_error(monkeypatch, caplog):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.request.GET = {'state': 'expected-state', 'code': 'authorization-code'}
    provider.store_in_session(provider.request, 'state', 'expected-state')
    provider.store_in_session(provider.request, 'request', ('get', provider.get_get_url()))

    class Response:
        status_code = 401
        content = b'{"error":"invalid_client"}'

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

        def json(self):
            return {'error': 'invalid_client'}

    monkeypatch.setattr('rdmo.services.providers.requests.post', lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        'rdmo_radar.exports.providers.render',
        lambda request, template, context, status: (template, context, status)
    )

    template, context, status = provider.callback(provider.request)

    assert template == 'core/error.html'
    assert status == 200
    assert context['title'] == 'RADAR OAuth error'
    assert 'configured OAuth client' in str(context['errors'][0])
    assert 'status=401 error=invalid_client' in caplog.text
    assert 'client-secret' not in caplog.text
    assert 'authorization-code' not in caplog.text


def test_oauth_callback_renders_invalid_grant_error(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.request.GET = {'state': 'expected-state', 'code': 'authorization-code'}
    provider.store_in_session(provider.request, 'state', 'expected-state')

    class Response:
        status_code = 400
        content = b'{"error":"invalid_grant"}'

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

        def json(self):
            return {'error': 'invalid_grant'}

    monkeypatch.setattr('rdmo.services.providers.requests.post', lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        'rdmo_radar.exports.providers.render',
        lambda request, template, context, status: context
    )

    context = provider.callback(provider.request)

    assert 'authorization code or redirect URI' in str(context['errors'][0])


def test_credentials_provider_uses_json_api_and_registered_url():
    provider = make_provider()

    assert provider.token_url == 'https://radar.example.test/radar/api/tokens'
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


def test_credentials_are_exchanged_without_being_stored(monkeypatch):
    provider = make_provider({
        'stage': 'credentials',
        'username': 'radar-user',
        'password': 'radar-password'
    })
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'access_token': 'bearer-token', 'refresh_token': 'unused-refresh-token'}

    def post(url, **kwargs):
        captured['url'] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr('rdmo_radar.exports.credentials.requests.post', post)
    monkeypatch.setattr('rdmo_radar.exports.credentials.redirect', lambda *args: args)

    result = provider.submit_credentials_form()

    assert result == ('project_export', 1, 'radar')
    assert captured == {
        'url': 'https://radar.example.test/radar/api/tokens',
        'json': {
            'clientId': 'configured-client-id',
            'clientSecret': 'client-secret',
            'userName': 'radar-user',
            'userPassword': 'radar-password',
            'redirectUrl': 'https://rdmo.example.test/'
        },
        'timeout': 30
    }
    assert provider.request.session == {
        'rdmo_radar.exports.RadarCredentialsExportProvider.access_token': 'bearer-token'
    }
    assert 'radar-password' not in repr(provider.request.session)
    assert 'unused-refresh-token' not in repr(provider.request.session)


def test_failed_login_does_not_store_credentials(monkeypatch):
    provider = make_provider({
        'stage': 'credentials',
        'username': 'radar-user',
        'password': 'wrong-password'
    })

    def post(*args, **kwargs):
        raise requests.HTTPError

    monkeypatch.setattr('rdmo_radar.exports.credentials.requests.post', post)
    monkeypatch.setattr(provider, 'render_credentials_form', lambda form: form)

    form = provider.submit_credentials_form()

    assert not form.is_valid()
    assert form.non_field_errors()
    assert provider.request.session == {}


def test_workspace_request_uses_bearer_token(monkeypatch):
    provider = make_provider()
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    provider.store_in_session(provider.request, 'dataset_choices', [(0, 'Dataset')])
    provider.store_in_session(provider.request, 'radar_urls', [None])
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'data': [{'id': 'workspace-1', 'descriptiveMetadata': {'title': 'Workspace'}}]}

    def get(url, **kwargs):
        captured['url'] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr('rdmo_radar.exports.credentials.requests.get', get)
    monkeypatch.setattr(
        'rdmo_radar.exports.credentials.render',
        lambda request, template, context, status: context
    )

    context = provider.render_export_form()

    assert captured['headers'] == {'Authorization': 'Bearer bearer-token'}
    assert captured['timeout'] == 30
    assert context['form'].fields['workspace'].widget.choices == [('workspace-1', 'Workspace')]


def test_workspace_request_failure_clears_export_session(monkeypatch):
    provider = make_provider()
    provider.store_in_session(provider.request, 'access_token', 'expired-token')
    provider.store_in_session(provider.request, 'dataset_choices', [(0, 'Dataset')])
    provider.store_in_session(provider.request, 'radar_urls', [None])
    provider.store_in_session(provider.request, 'project_id', 1)

    def get(*args, **kwargs):
        raise requests.HTTPError

    monkeypatch.setattr('rdmo_radar.exports.credentials.requests.get', get)
    monkeypatch.setattr(provider, 'render_credentials_form', lambda form=None, error=None: error)

    error = provider.render_export_form()

    assert error
    assert provider.request.session == {}


def test_cancel_clears_export_session(monkeypatch):
    provider = make_provider({'cancel': '1'})
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    provider.store_in_session(provider.request, 'dataset_choices', [(0, 'Dataset')])
    provider.store_in_session(provider.request, 'project_id', 1)
    monkeypatch.setattr('rdmo_radar.exports.credentials.redirect', lambda *args: args)

    result = provider.submit()

    assert result == ('project', 1)
    assert provider.request.session == {}


def test_dataset_export_clears_bearer_token(monkeypatch):
    provider = make_provider({
        'stage': 'export',
        'dataset': '0',
        'workspace': 'workspace-1'
    })
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')
    provider.store_in_session(provider.request, 'dataset_choices', [(0, 'Dataset')])
    provider.store_in_session(provider.request, 'workspace_choices', [('workspace-1', 'Workspace')])
    provider.store_in_session(provider.request, 'radar_urls', [None])
    provider.store_in_session(provider.request, 'project_id', 1)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def post(url, **kwargs):
        captured['url'] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr('rdmo_radar.exports.credentials.requests.post', post)
    monkeypatch.setattr(provider, 'get_post_data', lambda set_index: {'descriptiveMetadata': {'title': 'Dataset'}})
    monkeypatch.setattr(provider, 'post_success', lambda request, response: 'success')

    result = provider.submit_export_form()

    assert result == 'success'
    assert captured['url'].endswith('/radar/api/workspaces/workspace-1/datasets')
    assert captured['headers'] == {'Authorization': 'Bearer bearer-token'}
    assert captured['timeout'] == 30
    assert provider.request.session == {}


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


def test_dataset_resource_type_uses_standard_mapping():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    option_mappings = []

    export.get_set = lambda *args, **kwargs: []
    export.get_values = lambda *args, **kwargs: []
    export.get_list = lambda *args, **kwargs: []
    export.get_year = lambda *args, **kwargs: None
    export.get_text = lambda path, **kwargs: 'Resource' if path.endswith('/resource_type') else None

    def get_option(options, path, **kwargs):
        option_mappings.append(options)
        return 'Dataset'

    export.get_option = get_option

    dataset = export.get_dataset(0)

    assert dataset['resource'] == {'value': 'Resource', 'resourceType': 'Dataset'}
    assert export.resource_type_general_options in option_mappings
    assert export.data_source_options['radar_data_source/trial'] == 'Trial'
    assert export.data_source_options['radar_data_source/organism'] == 'Organism'
    assert export.data_source_options['radar_data_source/tissue'] == 'Tissue'


def test_structured_name_keeps_primary_name():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    values = {
        'project/dataset/creator/name': 'Doe, Jane',
        'project/dataset/creator/given_name': 'Jane',
        'project/dataset/creator/family_name': 'Doe',
    }
    export.get_text = lambda path, **kwargs: values.get(path)
    export.get_list = lambda *args, **kwargs: []
    export.get_option = lambda *args, **kwargs: None

    name = export.get_name('creator', 'project/dataset/creator')

    assert name['creatorName'] == 'Doe, Jane'
    assert name['givenName'] == 'Jane'
    assert name['familyName'] == 'Doe'


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
            'contributorType': 'DATA_MANAGER',
        }]},
    })
    root = ElementTree.fromstring(xml)
    namespace = {'radar': 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'}

    assert root.findtext('.//radar:creatorName', namespaces=namespace) == 'Doe, Jane'
    contributor = root.find('.//radar:contributor', namespace)
    assert contributor.attrib['contributorType'] == 'DATA_MANAGER'
    assert contributor.findtext('radar:contributorName', namespaces=namespace) == 'Smith, John'
    assert capsys.readouterr().out == ''


def test_zip_export_is_complete_and_readable():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = SimpleNamespace(title='Project')
    export.get_set = lambda *args, **kwargs: [SimpleNamespace(set_index=0)]
    export.get_text = lambda path, **kwargs: 'dataset-id' if path.endswith('/id') else None
    export.get_dataset = lambda set_index: {'title': 'Dataset'}

    response = export.render()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['dataset-id.xml']
        assert b'<title>Dataset</title>' in archive.read('dataset-id.xml')
