import json
import logging
from dataclasses import asdict
from functools import partial
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

import requests

from rdmo.projects.exports import Export
from rdmo.projects.models import Project
from rdmo.services.providers import OauthProviderMixin

from rdmo_radar.client import dataset_page_url, dataset_url, workspace_choices, workspaces_url
from rdmo_radar.exceptions import ExportStoreError, RadarProtocolError
from rdmo_radar.factories import build_export_service
from rdmo_radar.mappings import ExportDataset, validate_datasets
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING
from rdmo_radar.metadata.validation import missing_required_fields
from rdmo_radar.services import store_confirmed_result

from .validation import REQUIRED_FIELD_LABELS

logger = logging.getLogger(__name__)


class RadarExportProviderBase(Export):
    mapping = TEMPLATE_FRAMEWORK_MAPPING
    show_mapping_warnings = None

    def get_service(self):
        if self.project is None and self.snapshot is not None:
            self.project = self.snapshot.project
        key = (id(self.project), self.snapshot, self.project.catalog_id, id(self.mapping))
        if getattr(self, '_service_key', None) != key:
            self._service = build_export_service(self.project, snapshot=self.snapshot, profile=self.mapping)
            self._service_key = key
        return self._service

    def get_context(self, dataset):
        """Read the selected dataset using the operation's prepared RDMO Values."""
        return self.get_service().reader(dataset)

    def get_payload(self, dataset) -> dict:
        """Return the complete RADAR REST request body, ready for submission."""
        return self.get_service().compute_payload(dataset, self.request.user.email).payload

    def _prepare_payload(self, dataset, form):
        try:
            payload = self.get_payload(dataset)
            if not isinstance(payload, dict):
                raise TypeError('The RADAR request payload must be a dictionary.')
            json.dumps(payload, allow_nan=False)
        except Exception:
            logger.warning('Could not prepare RADAR export payload: provider=%s', self.class_name)
            form.add_error(None, _('The RADAR export could not be prepared. Please contact an administrator.'))
            return None
        return payload

    def get_dataset_indices(self):
        return sorted({dataset.scope['set_index'] for dataset in self.get_datasets()})

    def get_datasets(self):
        """Return the datasets that this mapping can export from the RDMO project."""
        service = self.get_service()
        if getattr(self, '_dataset_service', None) is not service:
            self._datasets = validate_datasets(self.mapping.get_datasets(self.project, service.reader))
            self._dataset_service = service
        return self._datasets

    def get_selected_dataset(self, form):
        if self.get_from_session(self.request, 'project_id') != self.project.pk:
            form.add_error(None, _('The export selection has changed. Please reload the export form.'))
            return None
        for dataset in self.get_datasets():
            if dataset.key == form.cleaned_data['dataset']:
                return dataset
        form.add_error('dataset', _('This dataset is no longer available. Please reload the export form.'))
        return None

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
        datasets = self.get_datasets()
        dataset_choices = [(dataset.key, dataset.label) for dataset in datasets]
        radar_urls = [dataset.radar_url for dataset in datasets]

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
        show_warnings = self.show_mapping_warnings
        if show_warnings is None:
            show_warnings = type(self).get_payload is RadarExportProviderBase.get_payload
        if not show_warnings:
            return []
        warnings = []
        for dataset in self.get_datasets():
            service = self.get_service()
            result = service.mapping(service.reader(dataset))
            metadata = result.metadata
            missing = missing_required_fields(metadata)
            if missing or result.issues:
                warnings.append({
                    'title': metadata.title or dataset.label,
                    'issues': result.issues,
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
            'operation',
            'export_context',
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

    def get_workspace_choices(self, response):
        try:
            data = response.json()
        except ValueError:
            raise RadarProtocolError() from None
        if not isinstance(data, dict):
            raise RadarProtocolError()
        return workspace_choices(data)

    def get_get_url(self):
        return workspaces_url(self.radar_url)

    def post_success(self, request, response):
        try:
            data = response.json()
        except ValueError:
            data = None
        radar_id = data.get('id') if isinstance(data, dict) else None
        if not isinstance(radar_id, str) or not radar_id.strip():
            return render(request, 'core/error.html', {
                'title': _('RADAR error'),
                'errors': [self.get_client_error_message(RadarProtocolError(), stage='export')],
            }, status=200)
        context = self.get_from_session(request, 'export_context')
        radar_url = dataset_page_url(context['radar_url'], radar_id, context['language'])
        stored = True
        try:
            dataset = ExportDataset(**context['dataset'])
            if context['provider'] != self.class_name:
                raise ExportStoreError(dataset.key, radar_id, radar_url)
            if context['persist']:
                if self.mapping.store_result is None:
                    raise ExportStoreError(dataset.key, radar_id, radar_url)
                project = Project.objects.get(pk=context['project_id'])
                writer = partial(self.mapping.store_result, project)
                store_confirmed_result(writer, dataset, radar_id, radar_url)
        except (Project.DoesNotExist, DatabaseError, ExportStoreError, KeyError, TypeError, ValueError):
            logger.warning('Could not store confirmed RADAR dataset %s', radar_id)
            stored = False
        self.pop_from_session(request, 'export_context')
        self.pop_from_session(request, 'operation')
        return self.render_export_result(request, radar_id, radar_url, stored=stored)

    def render_export_result(self, request, radar_id, radar_url, *, stored=True):
        if stored:
            return redirect(radar_url)
        return render(request, 'plugins/exports_radar_result.html', {
            'radar_id': radar_id, 'radar_url': radar_url,
        })

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

    def get_client_error_message(self, error, *, stage='request'):
        response = getattr(error, 'response', None)
        status = response.status_code if response is not None else None
        logger.warning('RADAR request failed: status=%s', status)
        if stage == 'oauth':
            return _('RADAR OAuth authorization could not be completed. Please try again or contact an administrator.')
        if status == 401 or (stage == 'login' and status == 400):
            return _('RADAR login failed or expired. Please check your credentials and log in again.')
        if status == 403:
            return _('Your RADAR account does not have permission for this operation. Check workspace access.')
        if stage == 'export' and status in (400, 422):
            return _('RADAR rejected the dataset metadata. Review the metadata and mapping warnings before retrying.')
        if stage == 'export':
            return _('The RADAR export could not be confirmed. Check RADAR for an existing draft before retrying.')
        return _('RADAR could not complete the request. Please try again later.')


class RadarExportProvider(RadarExportProviderBase, OauthProviderMixin):

    oauth_token_auth_methods = ('client_secret_basic', 'client_secret_post')

    def authorize(self, request):
        callback = urlsplit(self.redirect_uri)
        current = urlsplit(request.build_absolute_uri('/'))
        default_ports = {'http': 80, 'https': 443}
        callback_origin = (callback.scheme, callback.hostname, callback.port or default_ports.get(callback.scheme))
        current_origin = (current.scheme, current.hostname, current.port or default_ports.get(current.scheme))
        if callback_origin != current_origin:
            return render(request, 'core/error.html', {
                'title': _('RADAR OAuth configuration error'),
                'errors': [_(
                    'The configured RADAR OAuth callback points to a different RDMO instance. '
                    'Start the export on that instance or ask an administrator to configure '
                    'and register a callback URL for this instance.'
                )],
            }, status=200)
        return super().authorize(request)

    def callback(self, request):
        self.request = request
        try:
            return super().callback(request)
        except requests.RequestException as error:
            message = self.get_client_error_message(error, stage='oauth')
            if self.get_from_session(request, 'operation') == 'create_dataset':
                message = '{} {}'.format(message, _(
                    'The RADAR export could not be confirmed. Check RADAR for an existing draft before retrying.'
                ))
            return render(request, 'core/error.html', {
                'title': _('RADAR OAuth error'),
                'errors': [message],
            }, status=200)

    def render(self):
        self.prepare_export_session()

        if self.pop_from_session(self.request, 'get') is True:
            form = self.get_export_form()
            return render(self.request, 'plugins/exports_radar.html', {'form': form}, status=200)

        self.store_in_session(self.request, 'operation', 'get_workspaces')
        return self.get(self.request, self.get_get_url())

    def submit(self):
        form = self.get_export_form(data=self.request.POST)

        if 'cancel' in self.request.POST:
            self.pop_from_session(self.request, 'get')
            self.pop_from_session(self.request, 'workspace_choices')
            self.pop_from_session(self.request, 'export_context')
            return redirect('project', self.project.id)

        if form.is_valid():
            dataset = self.get_selected_dataset(form)
            if dataset is None:
                return render(self.request, 'plugins/exports_radar.html', {'form': form}, status=200)
            radar_url = self.radar_url
            payload = self._prepare_payload(dataset, form)
            if payload is None:
                return render(self.request, 'plugins/exports_radar.html', {'form': form}, status=200)
            self.store_in_session(self.request, 'export_context', {
                'project_id': self.project.pk, 'dataset': asdict(dataset),
                'provider': self.class_name, 'persist': self.mapping.store_result is not None,
                'radar_url': radar_url, 'language': self.request.LANGUAGE_CODE,
            })
            self.store_in_session(self.request, 'operation', 'create_dataset')
            return self.post(
                self.request, dataset_url(radar_url, form.cleaned_data['workspace']), payload,
            )

        return render(self.request, 'plugins/exports_radar.html', {'form': form}, status=200)

    def get_success(self, request, response):
        try:
            choices = self.get_workspace_choices(response)
        except RadarProtocolError as error:
            return render(request, 'core/error.html', {
                'title': _('RADAR error'), 'errors': [self.get_client_error_message(error)],
            }, status=200)
        self.store_in_session(request, 'get', True)
        self.store_in_session(request, 'workspace_choices', choices)
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
        stage = 'export' if self.get_from_session(self.request, 'operation') == 'create_dataset' else 'request'
        return self.get_client_error_message(requests.HTTPError(response=response), stage=stage)


class RadarProjectExportProvider(RadarExportProvider):
    mapping = PROJECT_MAPPING


class RadarTemplateFrameworkExportProvider(RadarExportProvider):
    mapping = TEMPLATE_FRAMEWORK_MAPPING
