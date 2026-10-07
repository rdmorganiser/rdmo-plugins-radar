import logging
import time

from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect, render
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

import requests

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value
from rdmo.services.providers import OauthProviderMixin

from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.constants import APIVocabulary
from rdmo_radar.metadata.values import get_answer_index
from rdmo_radar.metadata.xml import missing_required_fields, to_xml_payload

from .exports import REQUIRED_FIELD_LABELS, RadarExport

logger = logging.getLogger(__name__)


class RadarExportProviderBase(APIVocabulary, RadarExport):
    def get_dataset(self, set_index):
        set_index = int(set_index)
        metadata = self.compute_metadata(set_index)
        if not metadata.title:
            metadata.title = f'Dataset #{set_index + 1}'
        return to_api_payload(metadata)

    class Form(forms.Form):
        dataset = forms.ChoiceField(label=_('Select dataset of your project'))
        workspace = forms.ChoiceField(label=_('Select a workspace in RADAR'))

        def __init__(self, *args, **kwargs):
            dataset_choices = kwargs.pop('dataset_choices')
            workspace_choices = kwargs.pop('workspace_choices')
            radar_urls = kwargs.pop('radar_urls')
            self.mapping_warnings = kwargs.pop('mapping_warnings', [])

            super().__init__(*args, **kwargs)

            dataset_choices_with_radar_urls = []
            for dataset, radar_url in zip(dataset_choices, radar_urls, strict=False):
                set_index, label = dataset
                if radar_url is not None:
                    label = format_html(
                        '{} (Already exported to RADAR: <a href="{}" target="_blank" '
                        'rel="noopener noreferrer">{}</a>)',
                        label,
                        radar_url,
                        radar_url
                    )
                dataset_choices_with_radar_urls.append((set_index, label))

            self.fields['dataset'].widget = forms.RadioSelect()
            self.fields['dataset'].choices = dataset_choices_with_radar_urls
            self.fields['workspace'].widget = forms.RadioSelect()
            self.fields['workspace'].choices = workspace_choices

    def prepare_export_session(self):
        indices = self.get_dataset_indices()
        dataset_choices = [(index, self.get_dataset_title(index) or f'Dataset #{index + 1}') for index in indices]
        radar_urls = [self.get_text('project/dataset/radar_url', set_index=index) for index in indices]

        self.store_in_session(self.request, 'dataset_choices', dataset_choices)
        self.store_in_session(self.request, 'radar_urls', radar_urls)
        self.store_in_session(self.request, 'project_id', self.project.id)

    def get_export_form(self, data=None, workspace_choices=None):
        return self.Form(
            data,
            dataset_choices=self.get_from_session(self.request, 'dataset_choices') or [],
            workspace_choices=workspace_choices or self.get_from_session(self.request, 'workspace_choices') or [],
            radar_urls=self.get_from_session(self.request, 'radar_urls') or [],
            mapping_warnings=self.get_mapping_warnings(),
        )

    def get_mapping_warnings(self):
        if get_answer_index(self) is None:
            return []
        warnings = []
        for index in self.get_dataset_indices():
            metadata = self.compute_metadata(index)
            missing = missing_required_fields(to_xml_payload(metadata))
            if missing or metadata.mapping_issues:
                warnings.append({
                    'title': metadata.title or f'Dataset #{index + 1}',
                    'issues': metadata.mapping_issues,
                    'missing': [REQUIRED_FIELD_LABELS.get(path, path) for path in missing],
                })
        return warnings

    def clear_session(self, request):
        for key in (
            'access_token',
            'dataset_choices',
            'workspace_choices',
            'radar_urls',
            'project_id',
            'set_index'
        ):
            self.pop_from_session(request, key)

    def get_session_key(self, key):
        return f'{self.class_name}.{key}'

    def store_in_session(self, request, key, data):
        request.session[self.get_session_key(key)] = data

    def get_from_session(self, request, key):
        return request.session.get(self.get_session_key(key))

    def pop_from_session(self, request, key):
        return request.session.pop(self.get_session_key(key), None)

    def get_authorization_headers(self, access_token):
        return {'Authorization': f'Bearer {access_token}'}

    def get_workspace_choices(self, response):
        return [
            (workspace.get('id'), workspace.get('descriptiveMetadata', {}).get('title'))
            for workspace in response.json().get('data', [])
        ]

    def get_get_url(self):
        return f'{self.radar_url}/radar/api/workspaces?rows=100&sort=descriptiveMetadata.title'

    def get_post_url(self, workspace_id):
        return f'{self.radar_url}/radar/api/workspaces/{workspace_id}/datasets'

    def get_post_data(self, set_index):
        now = int(time.time() * 1000)
        email = self.request.user.email
        dataset = self.get_dataset(set_index)

        return {
            'technicalMetadata': {
                "retentionPeriod": 10,
                "archiveDate": now,
                "publishDate": now,
                "responsibleEmail": email,
                "schema": {
                    "key": "RDDM",
                    "version": "9.3"
                }
            },
            'descriptiveMetadata': dataset
        }

    def post_success(self, request, response):
        radar_id = response.json().get('id')
        if radar_id:
            project_id = self.get_from_session(self.request, 'project_id')
            set_index = self.get_from_session(self.request, 'set_index')

            if request.LANGUAGE_CODE == 'de':
                radar_url = f'{self.radar_url}/radar/de/dataset/{radar_id}'
            else:
                radar_url = f'{self.radar_url}/radar/en/dataset/{radar_id}'

            try:
                attribute = Attribute.objects.get(path='project/dataset/radar_id')
                value, _created = Value.objects.get_or_create(
                    attribute=attribute,
                    project_id=project_id,
                    set_index=set_index
                )
                value.text = radar_id
                value.save()
            except Attribute.DoesNotExist:
                pass

            try:
                attribute = Attribute.objects.get(path='project/dataset/radar_url')
                value, _created = Value.objects.get_or_create(
                    attribute=attribute,
                    project_id=project_id,
                    set_index=set_index
                )
                value.text = radar_url
                value.save()
            except Attribute.DoesNotExist:
                pass

            return redirect(radar_url)
        else:
            return render(request, 'core/error.html', {
                'title': _('RADAR error'),
                'errors': [_('The ID of the new dataset could not be retrieved.')]
            }, status=200)

    @property
    def radar_url(self):
        return settings.RADAR_PROVIDER['radar_url'].strip('/')

    @property
    def client_id(self):
        return settings.RADAR_PROVIDER['client_id']

    @property
    def client_secret(self):
        return settings.RADAR_PROVIDER['client_secret']

    @property
    def request_timeout(self):
        return settings.RADAR_PROVIDER.get('request_timeout', 30)


class RadarExportProvider(RadarExportProviderBase, OauthProviderMixin):

    oauth_token_auth_methods = ('client_secret_basic', 'client_secret_post')

    def callback(self, request):
        try:
            return super().callback(request)
        except requests.HTTPError as error:
            response = error.response
            status_code = response.status_code if response is not None else None

            try:
                error_code = response.json().get('error') if response is not None else None
            except (AttributeError, ValueError):
                error_code = None

            logger.error(
                'RADAR OAuth token exchange failed: status=%s error=%s',
                status_code,
                error_code or 'unknown'
            )

            if error_code == 'invalid_client':
                message = _(
                    'RADAR rejected the configured OAuth client. '
                    'Please contact an administrator.'
                )
            elif error_code == 'invalid_grant':
                message = _(
                    'RADAR rejected the authorization code or redirect URI. '
                    'Please try again or contact an administrator.'
                )
            else:
                message = _(
                    'RADAR OAuth authorization could not be completed. '
                    'Please try again or contact an administrator.'
                )

            return render(request, 'core/error.html', {
                'title': _('RADAR OAuth error'),
                'errors': [message]
            }, status=200)

    def render(self):
        self.prepare_export_session()

        if self.pop_from_session(self.request, 'get') is True:
            form = self.get_export_form()
            return render(self.request, 'plugins/exports_radar.html', {'form': form}, status=200)

        return self.get(self.request, self.get_get_url())

    def submit(self):
        form = self.get_export_form(data=self.request.POST)

        if 'cancel' in self.request.POST:
            self.pop_from_session(self.request, 'get')
            self.pop_from_session(self.request, 'workspace_choices')
            return redirect('project', self.project.id)

        if form.is_valid():
            self.store_in_session(self.request, 'set_index', form.cleaned_data['dataset'])
            return self.post(
                self.request,
                self.get_post_url(form.cleaned_data['workspace']),
                self.get_post_data(form.cleaned_data['dataset'])
            )

        return render(self.request, 'plugins/exports_radar.html', {'form': form}, status=200)

    def get_success(self, request, response):
        self.store_in_session(request, 'get', True)
        self.store_in_session(request, 'workspace_choices', self.get_workspace_choices(response))
        return redirect('project_export', self.get_from_session(request, 'project_id'), self.key)

    @property
    def authorize_url(self):
        return f'{self.radar_url}/radar-backend/oauth/authorize'

    @property
    def token_url(self):
        return f'{self.radar_url}/radar-backend/oauth/token'

    @property
    def redirect_uri(self):
        return settings.RADAR_PROVIDER['redirect_uri']

    @property
    def oauth_token_auth_method(self):
        auth_method = settings.RADAR_PROVIDER.get(
            'oauth_token_auth_method',
            'client_secret_basic'
        )
        if auth_method not in self.oauth_token_auth_methods:
            raise ImproperlyConfigured(
                'RADAR_PROVIDER["oauth_token_auth_method"] must be '
                '"client_secret_basic" or "client_secret_post".'
            )
        return auth_method

    def get_authorize_params(self, request, state):
        return {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'state': state
        }

    def get_callback_params(self, request):
        if self.oauth_token_auth_method == 'client_secret_post':
            return {}
        return self.get_callback_token_data(request)

    def get_callback_data(self, request):
        if self.oauth_token_auth_method == 'client_secret_basic':
            return {}
        return {
            **self.get_callback_token_data(request),
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

    def get_callback_token_data(self, request):
        return {
            'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri,
            'code': request.GET.get('code')
        }

    def get_callback_auth(self, request):
        if self.oauth_token_auth_method == 'client_secret_basic':
            return (self.client_id, self.client_secret)
        return None

    def get_error_message(self, response):
        response_data = response.json()
        return response_data.get('exception') or response_data.get('error')
