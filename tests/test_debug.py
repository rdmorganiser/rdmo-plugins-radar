"""Local debug forms must never authenticate, submit, or replay a RADAR request."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExportProvider

from .test_exports import export_provider, make_provider


@pytest.fixture
def debug_mode(settings, monkeypatch):
    settings.RADAR_DEBUG = True
    del settings.RADAR_PROVIDER
    http = Mock(side_effect=AssertionError('Local debug mode must not contact RADAR'))
    monkeypatch.setattr('requests.get', http)
    monkeypatch.setattr('requests.post', http)
    monkeypatch.setattr('rdmo_radar.exports.providers.render', lambda request, template, context, status: context)
    yield http
    http.assert_not_called()


@pytest.fixture(params=[RadarCredentialsExportProvider, RadarExportProvider])
def local_provider(request, debug_mode):
    provider = export_provider(request.param)
    provider.request.POST['workspace'] = 'local-workspace'
    provider.get_payload = Mock(side_effect=AssertionError('Unexpected payload preparation'))
    provider.get_service().writer = Mock()
    return provider


@pytest.mark.parametrize('django_debug', [False, True])
@pytest.mark.parametrize('authenticated', [False, True])
def test_debug_form_skips_authentication_and_ignores_real_workspace_choices(
    local_provider, settings, django_debug, authenticated,
):
    settings.DEBUG = django_debug
    provider = local_provider
    if not authenticated:
        provider.pop_from_session(provider.request, 'access_token')
    session = deepcopy(provider.request.session)

    form = provider.render()['form']

    assert not form.is_bound
    assert form.debug_mode
    assert not form.preview_payload
    assert not form.preview_source_answers
    assert list(form.fields['dataset'].choices) == [('0', 'Dataset')]
    assert list(form.fields['workspace'].choices) == [('local-workspace', 'Local workspace (debug)')]
    assert provider.get_from_session(provider.request, 'workspace_choices') == [('workspace-1', 'Workspace')]
    assert provider.get_from_session(provider.request, 'access_token') == ('bearer-token' if authenticated else None)
    assert not any('local-workspace' in str(value) for value in provider.request.session.values())
    # Only the ordinary dataset choices are refreshed on GET.
    session[provider.get_session_key('dataset_choices')] = [('0', 'Dataset')]
    assert provider.request.session == session
    provider.get_payload.assert_not_called()


@pytest.mark.parametrize('stage', ['credentials', 'export', None])
def test_debug_submission_is_blocked_before_authentication_or_payload_preparation(local_provider, stage):
    provider = local_provider
    provider.pop_from_session(provider.request, 'access_token')
    provider.request.POST.update(username='example-user', password='example-password')
    if stage is None:
        del provider.request.POST['stage']
    else:
        provider.request.POST['stage'] = stage
    session = deepcopy(provider.request.session)

    form = provider.submit()['form']

    assert form.is_bound
    assert form.data['dataset'] == '0'
    assert form.data['workspace'] == 'local-workspace'
    assert 'RADAR export is disabled in local debug mode.' in str(form.non_field_errors())
    assert provider.request.session == session
    provider.get_payload.assert_not_called()
    provider.get_service().writer.assert_not_called()


def test_local_workspace_is_form_only_and_rejected_after_debug_is_disabled(local_provider, settings):
    provider = local_provider
    session = deepcopy(provider.request.session)
    form = provider.get_export_form(data=provider.request.POST, workspace_choices=[('real-workspace', 'Real')])
    assert form.is_valid()
    assert form.cleaned_data['workspace'] == 'local-workspace'
    assert provider.request.session == session

    settings.RADAR_DEBUG = False
    form = provider.get_export_form(data=provider.request.POST)
    assert not form.debug_mode
    assert list(form.fields['workspace'].choices) == [('workspace-1', 'Workspace')]
    assert not form.is_valid()
    assert 'workspace' in form.errors


@pytest.mark.parametrize('method', ['get', 'post'])
def test_debug_callback_discards_pending_work_before_token_exchange_or_reader_preparation(debug_mode, method):
    provider = make_provider(provider_class=RadarExportProvider)
    provider.project = None  # RDMO reconstructs the provider for the callback.
    provider.get_service = Mock(side_effect=AssertionError('Callback prepared project Values'))
    provider.get_export_context = Mock(side_effect=AssertionError('Callback resolved an export destination'))
    pending = [method, 'https://radar.example.test/radar/api/workspaces']
    if method == 'post':
        pending += [{'technicalMetadata': {}, 'descriptiveMetadata': {'title': 'Queued'}}, None, None]
    for key, value in (
        ('request', pending), ('state', 'pending-state'), ('operation', 'create_dataset'),
        ('export_context', {'persist': True}), ('access_token', 'existing-token'),
    ):
        provider.store_in_session(provider.request, key, value)
    provider.request.GET = {'state': 'pending-state', 'code': 'authorization-code'}

    result = provider.callback(provider.request)

    assert result['title'] == 'Local RADAR debug mode'
    assert 'authentication and export are disabled' in str(result['errors'][0])
    for key in ('request', 'state', 'operation', 'export_context'):
        assert provider.get_from_session(provider.request, key) is None
    assert provider.get_from_session(provider.request, 'access_token') == 'existing-token'
    provider.get_service.assert_not_called()
    provider.get_export_context.assert_not_called()
