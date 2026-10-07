import io
import zipfile
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings

import requests

from rdmo.services.providers import OauthProviderMixin

from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExportProvider
from rdmo_radar.exports.client import (
    RadarAuthenticationError,
    RadarAuthorizationError,
    RadarMetadataRejected,
    RadarProtocolError,
    RadarRequestError,
)
from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import (
    get_radar_schema,
    get_radar_validation_errors,
    validate_radar_xml,
)
from rdmo_radar.metadata.constants import APIVocabulary, XMLVocabulary
from rdmo_radar.metadata.types import RadarMetadata

from .helpers import add_answer, complete_metadata, make_export


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
    provider.get_dataset_indices = lambda: []
    return provider


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


def test_oauth_render_redirects_and_preserves_workspace_request():
    provider = make_provider(provider_class=RadarExportProvider)
    provider.get_dataset_indices = lambda: []

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


def test_oauth_success_callback_handles_malformed_response(monkeypatch):
    provider = make_provider(provider_class=RadarExportProvider)
    monkeypatch.setattr('rdmo_radar.exports.providers.render',
                        lambda request, template, context, status: context)
    response = SimpleNamespace(json=lambda: ['invalid'])
    assert 'existing draft' in str(provider.post_success(provider.request, response)['errors'][0])
    assert 'try again later' in str(provider.get_success(provider.request, response)['errors'][0])


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


def fake_client(monkeypatch, **methods):
    client = SimpleNamespace(**methods)
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


def test_failed_login_does_not_store_credentials(monkeypatch):
    provider = make_provider({'stage': 'credentials', 'username': 'radar-user', 'password': 'wrong-password'})

    def authenticate(*args):
        raise RadarAuthenticationError('authenticate', 401)

    fake_client(monkeypatch, authenticate=authenticate)
    monkeypatch.setattr(provider, 'render_credentials_form', lambda form: form)
    form = provider.submit_credentials_form()
    assert not form.is_valid()
    assert form.non_field_errors()
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
        raise RadarAuthenticationError('get_workspaces', 401)

    fake_client(monkeypatch, get_workspaces=get_workspaces)
    monkeypatch.setattr(provider, 'render_credentials_form', lambda form=None, error=None: error)
    assert 'log in again' in str(provider.render_export_form())
    assert provider.get_from_session(provider.request, 'access_token') is None
    assert provider.get_from_session(provider.request, 'dataset_choices') == [(0, 'Dataset')]


@pytest.mark.parametrize('error_type', [RadarAuthorizationError, RadarRequestError, RadarProtocolError])
def test_workspace_non_authentication_failure_preserves_token(monkeypatch, error_type):
    provider = make_provider()
    provider.store_in_session(provider.request, 'access_token', 'bearer-token')

    def get_workspaces(token):
        raise error_type('get_workspaces')

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


def export_provider():
    provider = make_provider({'stage': 'export', 'dataset': '0', 'workspace': 'workspace-1'})
    for key, value in (
        ('access_token', 'bearer-token'), ('dataset_choices', [(0, 'Dataset')]),
        ('workspace_choices', [('workspace-1', 'Workspace')]), ('radar_urls', [None]), ('project_id', 1),
    ):
        provider.store_in_session(provider.request, key, value)
    provider.get_post_data = lambda index: {'descriptiveMetadata': {'title': 'Dataset'}}
    return provider


def test_dataset_export_clears_bearer_token(monkeypatch):
    provider = export_provider()
    captured = []

    def create_dataset(token, workspace, payload):
        captured.append((token, workspace, payload))
        return {'id': 'radar-1'}

    fake_client(monkeypatch, create_dataset=create_dataset)
    monkeypatch.setattr(provider, 'complete_export', lambda request, radar_id: ('success', radar_id))
    assert provider.submit_export_form() == ('success', 'radar-1')
    assert captured == [('bearer-token', 'workspace-1', {'descriptiveMetadata': {'title': 'Dataset'}})]
    assert provider.request.session == {}


@pytest.mark.parametrize('error_type', [RadarAuthorizationError, RadarMetadataRejected,
                                       RadarRequestError, RadarProtocolError])
def test_dataset_failure_keeps_bound_form_and_token(monkeypatch, error_type):
    provider = export_provider()
    calls = []

    def create_dataset(*args):
        calls.append(args)
        raise error_type('create_dataset')

    fake_client(monkeypatch, create_dataset=create_dataset)
    monkeypatch.setattr('rdmo_radar.exports.credentials.render', lambda request, template, context, status: context)
    context = provider.submit_export_form()
    assert len(calls) == 1
    assert context['form'].is_bound
    assert context['form'].cleaned_data['dataset'] == '0'
    assert context['form'].cleaned_data['workspace'] == 'workspace-1'
    assert provider.get_from_session(provider.request, 'access_token') == 'bearer-token'
    assert 'log in' not in str(context['error'])
    if error_type in (RadarRequestError, RadarProtocolError):
        assert 'existing draft' in str(context['error'])


def test_dataset_authentication_failure_returns_to_credentials(monkeypatch):
    provider = export_provider()

    def create_dataset(*args):
        raise RadarAuthenticationError('create_dataset', 401)

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
    monkeypatch.setattr('rdmo_radar.exports.providers.time.time', lambda: 1_725_000_000.123)
    monkeypatch.setattr(provider, 'get_dataset', lambda set_index: {'title': 'Draft dataset'})

    payload = provider.get_post_data(0)

    assert payload['technicalMetadata']['schema'] == {'key': 'RDDM', 'version': '9.3'}
    assert payload['technicalMetadata']['archiveDate'] == 1_725_000_000_123
    assert payload['technicalMetadata']['publishDate'] == 1_725_000_000_123
    assert payload['descriptiveMetadata'] == {'title': 'Draft dataset'}


def test_direct_draft_omits_unavailable_descriptive_metadata():
    provider = make_provider()
    provider.compute_metadata = lambda index: RadarMetadata()
    assert provider.get_dataset(0) == {'title': 'Dataset #1'}


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
    assert export.get_dataset(0)['resource'] == {'value': 'Resource', 'resourceType': None}
    assert export.compute_metadata(0).mapping_issues == []
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
    name = export.compute_metadata(0).creators[0]
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
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = SimpleNamespace(title='Project')
    export.get_dataset_indices = lambda: [0, 1]
    export.get_dataset_title = lambda set_index: f'dataset-{set_index + 1}'
    export.compute_metadata = lambda set_index: complete_metadata(title=f'Dataset {set_index + 1}')

    response = export.render()
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['dataset-1.xml', 'dataset-2.xml']
        assert b'<re:title>Dataset 1</re:title>' in archive.read('dataset-1.xml')
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
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = SimpleNamespace(pk=1, title='Project', get_absolute_url=lambda: '/projects/1/')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/')
    export.get_dataset_indices = lambda: [0, 1]
    export.get_dataset_title = lambda set_index: f'dataset-{set_index + 1}'
    export.compute_metadata = lambda set_index: \
        complete_metadata() if set_index == 0 else RadarMetadata(title='Incomplete dataset')
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
    assert [file.file_name for file in response.context['files']] == ['dataset-1.xml', 'dataset-2.xml']
    assert not response.context['files'][0].has_warnings
    assert response.context['files'][1].has_warnings
    assert {field.path for field in response.context['files'][1].missing_fields} >= {'identifier', 'creators.creator'}


def test_invalid_xml_export_can_be_downloaded_after_confirmation():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = SimpleNamespace(pk=1, title='Project', get_absolute_url=lambda: '/projects/1/')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/', {'download': '1'})
    export.get_dataset_indices = lambda: [0]
    export.get_dataset_title = lambda index: 'incomplete'
    export.compute_metadata = lambda index: RadarMetadata(title='Incomplete dataset')

    response = export.render()

    assert response.status_code == 200
    assert response['Content-Type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['incomplete.xml']
        xml_data = archive.read('incomplete.xml')
        assert b'<re:title>Incomplete dataset</re:title>' in xml_data
        assert validate_radar_xml(xml_data) is not None


def test_legacy_dataset_id_marker_reports_missing_required_metadata(monkeypatch):
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = SimpleNamespace(pk=1, title='Project', get_absolute_url=lambda: '/projects/1/')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/')
    export.get_dataset_indices = lambda: [0]
    export.get_dataset_title = lambda index: None
    export.compute_metadata = lambda index: RadarMetadata()
    monkeypatch.setattr(
        'rdmo_radar.exports.exports.render',
        lambda request, template, context: SimpleNamespace(status_code=200, context=context),
    )

    response = export.render()

    assert response.status_code == 200
    missing = response.context['files'][0].missing_fields
    assert ('Identifier type', 'identifier.identifierType') in {
        (str(field.label), field.path) for field in missing
    }
    assert any(field.path == 'title' for field in missing)


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
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = SimpleNamespace(pk=1, title='Project')
    export.request = RequestFactory().get('/projects/1/export/radar-xml/', {'download': '1'})
    export.get_dataset_indices = lambda: [0]
    export.get_dataset_title = lambda index: 'broken'
    export.compute_metadata = lambda index: (_ for _ in ()).throw(ValueError('internal details'))

    response = export.render()

    assert response.status_code == 400
    assert response['Content-Type'].startswith('text/plain')
    assert response.content == b'RADAR XML export could not generate "broken.xml".'
    assert b'internal details' not in response.content
    assert 'internal details' in caplog.text
