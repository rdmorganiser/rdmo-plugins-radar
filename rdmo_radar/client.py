"""RADAR HTTP client and shared response/URL helpers, independent of Django."""
from urllib.parse import quote

import requests

from .exceptions import RadarProtocolError


def workspace_choices(data: dict) -> list[tuple[str, str]]:
    """Parse workspace choices for credentials and existing OAuth callbacks."""
    workspaces = data.get('data')
    if not isinstance(workspaces, list):
        raise RadarProtocolError()
    choices = []
    for workspace in workspaces:
        if not isinstance(workspace, dict) or not isinstance(workspace.get('id'), str) or not workspace['id']:
            raise RadarProtocolError()
        metadata = workspace.get('descriptiveMetadata')
        title = metadata.get('title') if isinstance(metadata, dict) else None
        if not isinstance(title, str) or not title:
            raise RadarProtocolError()
        choices.append((workspace['id'], title))
    choices.sort(key=lambda choice: choice[1].casefold())
    return choices


def workspaces_url(radar_url: str) -> str:
    return f'{radar_url.rstrip("/")}/radar/api/workspaces'


def dataset_url(radar_url: str, workspace_id: str) -> str:
    return f'{radar_url.rstrip("/")}/radar/api/workspaces/{quote(workspace_id, safe="")}/datasets'


def dataset_page_url(radar_url: str, radar_id: str, language: str = 'en') -> str:
    """Build the human-facing URL from the instance used for remote creation."""
    url_language = 'de' if language == 'de' else 'en'
    return f'{radar_url.rstrip("/")}/radar/{url_language}/dataset/{radar_id}'


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

    def get(self, url: str, *, token=None, **kwargs) -> requests.Response:
        return self._request(requests.get, url, token=token, **kwargs)

    def post(self, url: str, *, token=None, **kwargs) -> requests.Response:
        return self._request(requests.post, url, token=token, **kwargs)

    def authenticate(self, username: str, password: str) -> str:
        response = self.post(self.token_url, json={
            'clientId': self.client_id,
            'clientSecret': self.client_secret,
            'userName': username,
            'userPassword': password,
            'redirectUrl': self.redirect_url,
        })
        data = self._read_json(response)
        token = data.get('access_token')
        if not isinstance(token, str) or not token.strip():
            raise RadarProtocolError()
        return token

    def get_workspaces(self, token: str) -> list[tuple[str, str]]:
        response = self.get(self.workspaces_url, token=token)
        return workspace_choices(self._read_json(response))

    def create_dataset(self, token: str, workspace_id: str, payload: dict) -> dict:
        response = self.post(self.dataset_url(workspace_id), token=token, json=payload)
        data = self._read_json(response)
        if not isinstance(data.get('id'), str) or not data['id'].strip():
            # Creation may already have succeeded: do not automatically retry.
            raise RadarProtocolError()
        return data

    def _request(self, request, url: str, *, token=None, **kwargs) -> requests.Response:
        if token is not None:
            headers = requests.structures.CaseInsensitiveDict(kwargs.get('headers') or {})
            headers['Authorization'] = f'Bearer {token}'
            kwargs['headers'] = headers
        kwargs.setdefault('timeout', self.timeout)
        response = request(url, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _read_json(response) -> dict:
        try:
            data = response.json()
        except ValueError:
            raise RadarProtocolError() from None
        if not isinstance(data, dict):
            raise RadarProtocolError()
        return data
