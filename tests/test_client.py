import json

import pytest

import requests

from rdmo_radar.exports.client import (
    RadarAuthenticationError,
    RadarAuthorizationError,
    RadarClient,
    RadarMetadataRejected,
    RadarProtocolError,
    RadarRequestError,
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

    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', post)
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

    monkeypatch.setattr('rdmo_radar.exports.client.requests.get', get)
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
    monkeypatch.setattr('rdmo_radar.exports.client.requests.get',
                        lambda *args, **kwargs: response({'data': workspaces}))
    assert client.get_workspaces('token') == [('a1', 'Alpha'), ('a2', 'alpha'), ('b', 'Beta'), ('z', 'zebra')]


def test_dataset_creation_contract_and_no_followup_validation(client, monkeypatch):
    calls = []
    payload = {'technicalMetadata': {'schema': {'key': 'RDDM', 'version': '9.3'}},
               'descriptiveMetadata': {'title': 'Draft'}}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response({'id': 'radar-1'}, 201)

    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', post)
    assert client.create_dataset('token', 'workspace/1', payload) == {'id': 'radar-1'}
    assert calls == [('https://radar.example.test/radar/api/workspaces/workspace%2F1/datasets', {
        'timeout': 17, 'headers': {'Authorization': 'Bearer token'}, 'json': payload,
    })]


@pytest.mark.parametrize(('status', 'error_type'), [
    (401, RadarAuthenticationError), (403, RadarAuthorizationError),
    (400, RadarMetadataRejected), (422, RadarMetadataRejected), (404, RadarRequestError),
    (429, RadarRequestError), (500, RadarRequestError),
])
def test_dataset_http_failure_classification(client, monkeypatch, status, error_type):
    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', lambda *args, **kwargs: response({}, status))
    with pytest.raises(error_type) as caught:
        client.create_dataset('token', 'workspace', {})
    assert caught.value.status == status
    assert caught.value.operation == 'create_dataset'


def test_token_rejection_is_not_metadata_rejection(client, monkeypatch):
    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', lambda *args, **kwargs: response(
        {'error': 'invalid_client'}, 400))
    with pytest.raises(RadarAuthenticationError) as caught:
        client.authenticate('user', 'password')
    assert caught.value.code == 'invalid_client'


@pytest.mark.parametrize('data', [{}, {'access_token': None}, {'access_token': 42}, {'access_token': ' '}])
def test_missing_or_invalid_token_is_protocol_error(client, monkeypatch, data):
    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', lambda *args, **kwargs: response(data))
    with pytest.raises(RadarProtocolError):
        client.authenticate('user', 'password')


@pytest.mark.parametrize('data', [{}, {'data': None}, {'data': {}}, {'data': [None]},
                                 {'data': [{'id': 'workspace'}]}, {'data': [{'id': 1}]}])
def test_malformed_workspace_response_is_not_an_empty_workspace_list(client, monkeypatch, data):
    monkeypatch.setattr('rdmo_radar.exports.client.requests.get', lambda *args, **kwargs: response(data))
    with pytest.raises(RadarProtocolError):
        client.get_workspaces('token')


def test_empty_workspace_list_is_valid(client, monkeypatch):
    monkeypatch.setattr('rdmo_radar.exports.client.requests.get', lambda *args, **kwargs: response({'data': []}))
    assert client.get_workspaces('token') == []


@pytest.mark.parametrize('data', [{}, {'id': None}, {'id': []}, {'id': ' '}])
def test_missing_dataset_id_is_not_retried(client, monkeypatch, data):
    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        return response(data, 201)

    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', post)
    with pytest.raises(RadarProtocolError):
        client.create_dataset('token', 'workspace', {})
    assert len(calls) == 1


@pytest.mark.parametrize('result', [response(body=b'not-json'), response([]), response('text')])
def test_malformed_json_response(client, monkeypatch, result):
    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', lambda *args, **kwargs: result)
    with pytest.raises(RadarProtocolError):
        client.create_dataset('token', 'workspace', {})


@pytest.mark.parametrize('error_type', [requests.Timeout, requests.ConnectionError])
def test_network_failures_are_sanitized_and_never_retried(client, monkeypatch, caplog, error_type):
    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        raise error_type('password token client-secret')

    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', post)
    with pytest.raises(RadarRequestError) as caught:
        client.create_dataset('token', 'workspace', {})
    assert len(calls) == 1
    assert 'password' not in str(caught.value)
    assert 'client-secret' not in caplog.text


def test_upstream_response_body_is_not_logged(client, monkeypatch, caplog):
    monkeypatch.setattr('rdmo_radar.exports.client.requests.post', lambda *args, **kwargs: response(
        {'error': 'password=secret', 'exception': 'Bearer private-token', 'message': 'client-secret'}, 400))
    with pytest.raises(RadarMetadataRejected) as caught:
        client.create_dataset('private-token', 'workspace', {})
    assert caught.value.code == 'unknown'
    assert 'operation=create_dataset status=400' in caplog.text
    for secret in ('password=secret', 'private-token', 'client-secret'):
        assert secret not in caplog.text
        assert secret not in str(caught.value)
