import json
from unittest.mock import Mock

import pytest

import requests

from rdmo_radar.client import RadarClient, dataset_page_url
from rdmo_radar.exceptions import RadarProtocolError


@pytest.mark.parametrize(('radar_url', 'language', 'expected'), [
    ('https://radar.example.test', 'en', 'https://radar.example.test/radar/en/dataset/confirmed'),
    ('https://radar.example.test/', 'de', 'https://radar.example.test/radar/de/dataset/confirmed'),
    ('https://radar-staging.example.test///', 'fr', 'https://radar-staging.example.test/radar/en/dataset/confirmed'),
    ('https://radar-staging.example.test/', 'de-DE', 'https://radar-staging.example.test/radar/en/dataset/confirmed'),
])
def test_dataset_page_url_preserves_instance_and_language_behavior(radar_url, language, expected):
    assert dataset_page_url(radar_url, 'confirmed', language) == expected


def test_dataset_page_url_defaults_to_english_and_preserves_id_interpolation():
    assert dataset_page_url('https://radar.example.test/', 'confirmed/id') == (
        'https://radar.example.test/radar/en/dataset/confirmed/id'
    )


@pytest.fixture
def client():
    return RadarClient('https://radar.example.test/', 'client-id', 'client-secret', 'https://rdmo.example.test/', 17)


def response(data=None, status=200, body=None):
    result = requests.Response()
    result.status_code = status
    result._content = body if body is not None else json.dumps(data).encode()
    return result


def test_authentication_request_contract(client, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response({'access_token': 'token', 'refresh_token': 'discarded'})

    monkeypatch.setattr('rdmo_radar.client.requests.post', post)
    assert client.authenticate('username', 'password') == 'token'
    assert calls == [('https://radar.example.test/radar/api/tokens', {
        'timeout': 17,
        'json': {'clientId': 'client-id', 'clientSecret': 'client-secret', 'userName': 'username',
                 'userPassword': 'password', 'redirectUrl': 'https://rdmo.example.test/'},
    })]


def test_workspace_request_contract(client, monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response({'data': [{'id': 'workspace', 'descriptiveMetadata': {'title': 'Workspace'}}]})

    monkeypatch.setattr('rdmo_radar.client.requests.get', get)
    assert client.get_workspaces('token') == [('workspace', 'Workspace')]
    assert calls == [('https://radar.example.test/radar/api/workspaces', {
        'timeout': 17, 'headers': {'Authorization': 'Bearer token'},
    })]


def test_workspace_choices_are_sorted_locally_and_stably(client, monkeypatch):
    workspaces = [
        {'id': 'z', 'descriptiveMetadata': {'title': 'zebra'}},
        {'id': 'a1', 'descriptiveMetadata': {'title': 'Alpha'}},
        {'id': 'b', 'descriptiveMetadata': {'title': 'Beta'}},
        {'id': 'a2', 'descriptiveMetadata': {'title': 'alpha'}},
    ]
    monkeypatch.setattr('rdmo_radar.client.requests.get',
                        lambda *args, **kwargs: response({'data': workspaces}))
    assert client.get_workspaces('token') == [('a1', 'Alpha'), ('a2', 'alpha'), ('b', 'Beta'), ('z', 'zebra')]


def test_dataset_creation_contract_and_no_followup_validation(client, monkeypatch):
    calls = []
    payload = {'technicalMetadata': {'schema': {'key': 'RDDM', 'version': '9.3'}},
               'descriptiveMetadata': {'title': 'Draft'}}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response({'id': 'radar-1'}, 201)

    monkeypatch.setattr('rdmo_radar.client.requests.post', post)
    assert client.create_dataset('token', 'workspace/1', payload) == {'id': 'radar-1'}
    assert calls == [('https://radar.example.test/radar/api/workspaces/workspace%2F1/datasets', {
        'timeout': 17, 'headers': {'Authorization': 'Bearer token'}, 'json': payload,
    })]


@pytest.mark.parametrize('status', [400, 401, 403, 422, 500])
def test_dataset_http_failure_uses_standard_requests_error(client, monkeypatch, status):
    result = response({}, status)
    monkeypatch.setattr('rdmo_radar.client.requests.post', lambda *args, **kwargs: result)
    with pytest.raises(requests.HTTPError) as caught:
        client.create_dataset('token', 'workspace', {})
    assert caught.value.response is result


def test_token_rejection_uses_standard_http_error(client, monkeypatch):
    result = response({'error': 'invalid_client'}, 400)
    monkeypatch.setattr('rdmo_radar.client.requests.post', lambda *args, **kwargs: result)
    with pytest.raises(requests.HTTPError) as caught:
        client.authenticate('user', 'password')
    assert caught.value.response is result


@pytest.mark.parametrize('data', [{}, {'access_token': None}, {'access_token': 42}, {'access_token': ' '}])
def test_missing_or_invalid_token_is_protocol_error(client, monkeypatch, data):
    monkeypatch.setattr('rdmo_radar.client.requests.post', lambda *args, **kwargs: response(data))
    with pytest.raises(RadarProtocolError):
        client.authenticate('user', 'password')


@pytest.mark.parametrize('data', [{}, {'data': None}, {'data': {}}, {'data': [None]},
                                 {'data': [{'id': 'workspace'}]}, {'data': [{'id': 1}]}])
def test_malformed_workspace_response_is_not_an_empty_workspace_list(client, monkeypatch, data):
    monkeypatch.setattr('rdmo_radar.client.requests.get', lambda *args, **kwargs: response(data))
    with pytest.raises(RadarProtocolError):
        client.get_workspaces('token')


def test_empty_workspace_list_is_valid(client, monkeypatch):
    monkeypatch.setattr('rdmo_radar.client.requests.get', lambda *args, **kwargs: response({'data': []}))
    assert client.get_workspaces('token') == []


@pytest.mark.parametrize('data', [{}, {'id': None}, {'id': []}, {'id': ' '}])
def test_missing_dataset_id_is_not_retried(client, monkeypatch, data):
    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        return response(data, 201)

    monkeypatch.setattr('rdmo_radar.client.requests.post', post)
    with pytest.raises(RadarProtocolError):
        client.create_dataset('token', 'workspace', {})
    assert len(calls) == 1


@pytest.mark.parametrize('result', [response(body=b'not-json'), response([]), response('text')])
def test_malformed_json_response(client, monkeypatch, result):
    monkeypatch.setattr('rdmo_radar.client.requests.post', lambda *args, **kwargs: result)
    with pytest.raises(RadarProtocolError):
        client.create_dataset('token', 'workspace', {})


@pytest.mark.parametrize('error_type', [requests.Timeout, requests.ConnectionError])
def test_network_failures_propagate_without_logging_or_retry(client, monkeypatch, caplog, error_type):
    calls = []
    error = error_type('password token client-secret')

    def post(*args, **kwargs):
        calls.append(args)
        raise error

    monkeypatch.setattr('rdmo_radar.client.requests.post', post)
    with pytest.raises(error_type) as caught:
        client.create_dataset('token', 'workspace', {})
    assert len(calls) == 1
    assert caught.value is error
    assert 'client-secret' not in caplog.text


def test_upstream_response_body_is_not_logged(client, monkeypatch, caplog):
    monkeypatch.setattr('rdmo_radar.client.requests.post', lambda *args, **kwargs: response(
        {'error': 'password=secret', 'exception': 'Bearer private-token', 'message': 'client-secret'}, 400))
    with pytest.raises(requests.HTTPError) as caught:
        client.create_dataset('private-token', 'workspace', {})
    assert caught.value.response.status_code == 400
    assert not caplog.records
    for secret in ('password=secret', 'private-token', 'client-secret'):
        assert secret not in caplog.text
        assert secret not in str(caught.value)


@pytest.mark.parametrize(('method', 'result'), [
    ('get', response(body=b'<html>Page</html>')),
    ('post', response(status=204, body=b'')),
])
def test_http_methods_return_raw_successful_responses(client, monkeypatch, method, result):
    send = Mock(return_value=result)
    monkeypatch.setattr(f'rdmo_radar.client.requests.{method}', send)
    assert getattr(client, method)('https://radar.example.test/custom') is result
    send.assert_called_once_with('https://radar.example.test/custom', timeout=17)


@pytest.mark.parametrize('method', ['get', 'post'])
def test_http_methods_merge_bearer_headers_and_accept_timeout_override(client, monkeypatch, method):
    result = response(status=204, body=b'')
    send = Mock(return_value=result)
    monkeypatch.setattr(f'rdmo_radar.client.requests.{method}', send)
    headers = {'authorization': 'Existing authorization', 'X-Request-ID': 'request-1'}
    kwargs = {'params': {'page': 2}} if method == 'get' else {'data': b'input'}

    assert getattr(client, method)(
        'https://radar.example.test/custom', token='new-token', headers=headers, timeout=9, **kwargs,
    ) is result

    actual = send.call_args.kwargs
    assert actual['timeout'] == 9
    assert dict(actual['headers']) == {'Authorization': 'Bearer new-token', 'X-Request-ID': 'request-1'}
    assert actual.get('params' if method == 'get' else 'data') == kwargs.get('params' if method == 'get' else 'data')
    assert headers == {'authorization': 'Existing authorization', 'X-Request-ID': 'request-1'}
    send.assert_called_once()


def test_http_method_preserves_headers_without_a_token(client, monkeypatch):
    send = Mock(return_value=response(status=204, body=b''))
    monkeypatch.setattr('rdmo_radar.client.requests.get', send)
    headers = {'Authorization': 'Custom authorization', 'Accept': 'text/html'}
    client.get('https://radar.example.test/custom', headers=headers)
    assert send.call_args.kwargs['headers'] == headers


@pytest.mark.parametrize('status', [401, 403, 500])
def test_raw_http_failure_uses_standard_http_error(client, monkeypatch, status):
    result = response(status=status, body=b'private response body')
    send = Mock(return_value=result)
    monkeypatch.setattr('rdmo_radar.client.requests.get', send)
    with pytest.raises(requests.HTTPError) as caught:
        client.get('https://radar.example.test/custom')
    assert caught.value.response is result
    send.assert_called_once()


def test_raw_http_transport_error_propagates_without_retry(client, monkeypatch):
    error = requests.HTTPError('private details', response=response(status=403))
    send = Mock(side_effect=error)
    monkeypatch.setattr('rdmo_radar.client.requests.post', send)
    with pytest.raises(requests.HTTPError) as caught:
        client.post('https://radar.example.test/custom')
    assert caught.value is error
    send.assert_called_once()


def test_endpoint_methods_delegate_to_public_http_methods(client, monkeypatch):
    post = Mock(side_effect=[response({'access_token': 'token'}), response({'id': 'confirmed'}, 201)])
    get = Mock(return_value=response({'data': []}))
    monkeypatch.setattr(client, 'post', post)
    monkeypatch.setattr(client, 'get', get)

    assert client.authenticate('user', 'password') == 'token'
    assert client.get_workspaces('token') == []
    assert client.create_dataset('token', 'workspace', {'title': 'Draft'}) == {'id': 'confirmed'}

    assert post.call_args_list[0].args == (client.token_url,)
    get.assert_called_once_with(client.workspaces_url, token='token')
    assert post.call_args_list[1].args == (client.dataset_url('workspace'),)
    assert post.call_args_list[1].kwargs == {
        'token': 'token', 'json': {'title': 'Draft'},
    }
