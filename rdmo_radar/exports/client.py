"""Small RADAR credentials/API client without Django workflow dependencies."""
import logging
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# Only recognized machine codes are safe to log; upstream text can contain secrets.
SAFE_ERROR_CODES = {'invalid_client', 'invalid_grant', 'invalid_token', 'unauthorized', 'access_denied'}


class RadarClientError(Exception):
    def __init__(self, operation: str, status: int | None = None, code: str = 'unknown'):
        self.operation = operation
        self.status = status
        self.code = code if code in SAFE_ERROR_CODES else 'unknown'
        super().__init__(f'{type(self).__name__}: operation={operation} status={status} code={self.code}')
        logger.warning('RADAR request failed: operation=%s status=%s code=%s category=%s',
                       operation, status, self.code, type(self).__name__)


class RadarRequestError(RadarClientError):
    pass


class RadarAuthenticationError(RadarClientError):
    pass


class RadarAuthorizationError(RadarClientError):
    pass


class RadarMetadataRejected(RadarRequestError):
    pass


class RadarProtocolError(RadarRequestError):
    pass


def error_for_response(response, operation: str) -> RadarClientError:
    """Interpret HTTP failures without exposing upstream exception/message text."""
    status = response.status_code
    try:
        data = response.json()
        code = data.get('error') if isinstance(data, dict) else None
    except ValueError:
        code = None
    if not isinstance(code, str):
        code = 'unknown'
    if status == 401 or (operation == 'authenticate' and status == 400 and code in SAFE_ERROR_CODES):
        return RadarAuthenticationError(operation, status, code)
    if status == 403:
        return RadarAuthorizationError(operation, status, code)
    if operation == 'create_dataset' and status in (400, 422):
        return RadarMetadataRejected(operation, status, code)
    return RadarRequestError(operation, status, code)


def workspace_choices(data: dict) -> list[tuple[str, str]]:
    """Parse workspace choices for credentials and existing OAuth callbacks."""
    workspaces = data.get('data')
    if not isinstance(workspaces, list):
        raise RadarProtocolError('get_workspaces')
    choices = []
    for workspace in workspaces:
        if not isinstance(workspace, dict) or not isinstance(workspace.get('id'), str) or not workspace['id']:
            raise RadarProtocolError('get_workspaces')
        metadata = workspace.get('descriptiveMetadata')
        title = metadata.get('title') if isinstance(metadata, dict) else None
        if not isinstance(title, str) or not title:
            raise RadarProtocolError('get_workspaces')
        choices.append((workspace['id'], title))
    return choices


def workspaces_url(radar_url: str) -> str:
    return f'{radar_url.rstrip("/")}/radar/api/workspaces?rows=100&sort=descriptiveMetadata.title'


def dataset_url(radar_url: str, workspace_id: str) -> str:
    return f'{radar_url.rstrip("/")}/radar/api/workspaces/{quote(workspace_id, safe="")}/datasets'


class RadarClient:
    def __init__(self, radar_url: str, client_id: str, client_secret: str, redirect_url: str, timeout=30):
        self.radar_url = radar_url.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_url = redirect_url
        self.timeout = timeout

    @property
    def token_url(self) -> str:
        return f'{self.radar_url}/radar/api/tokens'

    @property
    def workspaces_url(self) -> str:
        return workspaces_url(self.radar_url)

    def dataset_url(self, workspace_id: str) -> str:
        return dataset_url(self.radar_url, workspace_id)

    def authenticate(self, username: str, password: str) -> str:
        data = self._request('post', self.token_url, 'authenticate', json={
            'clientId': self.client_id,
            'clientSecret': self.client_secret,
            'userName': username,
            'userPassword': password,
            'redirectUrl': self.redirect_url,
        })
        token = data.get('access_token')
        if not isinstance(token, str) or not token.strip():
            raise RadarProtocolError('authenticate')
        return token

    def get_workspaces(self, token: str) -> list[tuple[str, str]]:
        return workspace_choices(self._request('get', self.workspaces_url, 'get_workspaces', token=token))

    def create_dataset(self, token: str, workspace_id: str, payload: dict) -> dict:
        data = self._request('post', self.dataset_url(workspace_id), 'create_dataset', token=token, json=payload)
        if not isinstance(data.get('id'), str) or not data['id'].strip():
            # Creation may already have succeeded: do not automatically retry.
            raise RadarProtocolError('create_dataset')
        return data

    def _request(self, method: str, url: str, operation: str, *, token: str | None = None, **kwargs) -> dict:
        if token is not None:
            kwargs['headers'] = {'Authorization': f'Bearer {token}'}
        try:
            response = getattr(requests, method)(url, timeout=self.timeout, **kwargs)
        except requests.RequestException as error:
            if error.response is not None:
                raise error_for_response(error.response, operation) from None
            raise RadarRequestError(operation) from None
        if not 200 <= response.status_code < 300:
            raise error_for_response(response, operation)
        try:
            data = response.json()
        except ValueError:
            raise RadarProtocolError(operation, response.status_code) from None
        if not isinstance(data, dict):
            raise RadarProtocolError(operation, response.status_code)
        return data
