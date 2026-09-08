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
from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import (
    get_radar_schema,
    get_radar_validation_errors,
    validate_radar_xml,
)


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
    assert '/metadata/validate' not in captured['url']
    assert provider.request.session == {}


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
    provider.get_set = lambda *args, **kwargs: []
    provider.get_values = lambda *args, **kwargs: []
    provider.get_list = lambda *args, **kwargs: []
    provider.get_year = lambda *args, **kwargs: None
    provider.get_text = lambda *args, **kwargs: None
    provider.get_option = lambda *args, **kwargs: None

    dataset = provider.get_dataset(0)

    assert dataset == {'title': 'Dataset #1'}


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
    export.get_text = lambda path, **kwargs: 'Resource' if path == 'project/dataset/description' else None

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
    assert export.data_source_options['radar_data_source/survey'] == 'Survey'
    assert export.resource_type_general_options['resource_type_general/computational_notebook'] == \
        'ComputationalNotebook'
    assert export.description_type_options['description_type/version_notes'] == 'VersionNotes'
    assert export.contributor_type_options['contributor_type/translator'] == 'Translator'
    assert export.related_identifier_type_options['identifier_type/raid'] == 'RAiD'
    assert export.related_identifier_type_options['identifier_type/swhid'] == 'SWHID'
    assert export.relation_type_options['relation_type/is_translation_of'] == 'IsTranslationOf'


def test_api_and_xml_mappings_are_kept_separate():
    xml_export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    api_export = make_provider()

    assert xml_export.language_options['language/en'] == 'eng'
    assert api_export.language_options['language/en'] == 'ENG'
    assert xml_export.resource_type_general_options['resource_type_general/dataset'] == 'Dataset'
    assert api_export.resource_type_general_options['resource_type_general/dataset'] == 'DATASET'
    assert xml_export.funder_identifier_scheme_options['name_identifier_scheme/insi'] == 'ISNI'
    assert xml_export.name_identifier_scheme_options['name_identifier_scheme/insi'] == 'Other'


def test_compute_metadata_keeps_primary_structured_name():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    values = {
        'project/dataset/creator/name': 'Doe, Jane',
        'project/dataset/creator/given_name': 'Jane',
        'project/dataset/creator/family_name': 'Doe',
    }
    export.get_text = lambda path, **kwargs: values.get(path)
    export.get_set = lambda path, **kwargs: [SimpleNamespace(set_prefix='0', set_index=0)] \
        if path == 'project/dataset/creator/name' else []
    export.get_values = lambda *args, **kwargs: []
    export.get_list = lambda *args, **kwargs: []
    export.get_option = lambda *args, **kwargs: None

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
    export.get_set = lambda *args, **kwargs: [
        SimpleNamespace(set_index=0),
        SimpleNamespace(set_index=1)
    ]
    export.get_text = lambda path, set_index=0, **kwargs: \
        f'dataset-{set_index + 1}' if path == 'project/dataset/title' else None
    export.get_dataset = lambda set_index: make_valid_xml_dataset(title=f'Dataset {set_index + 1}')

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
    export.get_set = lambda *args, **kwargs: [
        SimpleNamespace(set_index=0),
        SimpleNamespace(set_index=1)
    ]
    export.get_text = lambda path, set_index=0, **kwargs: \
        f'dataset-{set_index + 1}' if path == 'project/dataset/title' else None
    export.get_dataset = lambda set_index: \
        make_valid_xml_dataset() if set_index == 0 else {'title': 'Incomplete dataset'}
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
    export.get_set = lambda *args, **kwargs: [SimpleNamespace(set_index=0)]
    export.get_text = lambda path, **kwargs: 'incomplete' if path == 'project/dataset/title' else None
    export.get_dataset = lambda set_index: {'title': 'Incomplete dataset'}

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
    export.get_set = lambda path, **kwargs: [SimpleNamespace(set_index=0)] \
        if path == 'project/dataset/id' else []
    export.get_text = lambda *args, **kwargs: None
    export.get_dataset = lambda set_index: {}
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
    export.get_set = lambda *args, **kwargs: [SimpleNamespace(set_index=0)]
    export.get_text = lambda path, **kwargs: 'broken' if path == 'project/dataset/title' else None
    export.get_dataset = lambda set_index: (_ for _ in ()).throw(ValueError('internal details'))

    response = export.render()

    assert response.status_code == 400
    assert response['Content-Type'].startswith('text/plain')
    assert response.content == b'RADAR XML export could not generate "broken.xml".'
    assert b'internal details' not in response.content
    assert 'internal details' in caplog.text
