import logging
from urllib.parse import urlsplit, urlunsplit

from django import forms
from django.conf import settings
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

import requests

from rdmo_radar.client import RadarClient, dataset_page_url
from rdmo_radar.exceptions import ExportStoreError, RadarProtocolError
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING

from .providers import RadarExportProviderBase

logger = logging.getLogger(__name__)


class RadarCredentialsExportProvider(RadarExportProviderBase):

    class CredentialsForm(forms.Form):

        stage = forms.ChoiceField(
            choices=(('credentials', 'credentials'),),
            initial='credentials',
            widget=forms.HiddenInput
        )
        username = forms.CharField(label=_('RADAR username'))
        password = forms.CharField(label=_('RADAR password'), widget=forms.PasswordInput)

    class Form(RadarExportProviderBase.Form):

        stage = forms.ChoiceField(
            choices=(('export', 'export'),),
            initial='export',
            widget=forms.HiddenInput
        )

    def render(self):
        self.prepare_export_session()

        if self.get_from_session(self.request, 'access_token'):
            return self.render_export_form()

        return self.render_credentials_form()

    def submit(self):
        if 'cancel' in self.request.POST:
            self.clear_session(self.request)
            return redirect('project', self.project.id)

        if self.request.POST.get('stage') == 'export':
            return self.submit_export_form()

        return self.submit_credentials_form()

    def render_credentials_form(self, form=None, error=None):
        return render(self.request, 'plugins/exports_radar_credentials.html', {
            'form': form or self.CredentialsForm(),
            'error': error
        }, status=200)

    def submit_credentials_form(self):
        form = self.CredentialsForm(self.request.POST)
        if not form.is_valid():
            return self.render_credentials_form(form)

        try:
            access_token = self.client.authenticate(
                form.cleaned_data['username'], form.cleaned_data['password']
            )
        except (requests.RequestException, RadarProtocolError) as error:
            form.add_error(None, self.get_client_error_message(error, stage='login'))
            return self.render_credentials_form(form)

        self.store_in_session(self.request, 'access_token', access_token)
        return redirect('project_export', self.project.id, self.key)

    def render_export_form(self, form=None, error=None):
        if form is None:
            try:
                workspace_choices = self.client.get_workspaces(
                    self.get_from_session(self.request, 'access_token')
                )
            except (requests.RequestException, RadarProtocolError) as client_error:
                response = getattr(client_error, 'response', None)
                error = self.get_client_error_message(client_error)
                if response is not None and response.status_code == 401:
                    self.pop_from_session(self.request, 'access_token')
                    return self.render_credentials_form(error=error)
                form = self.get_export_form()
            else:
                self.store_in_session(self.request, 'workspace_choices', workspace_choices)
                form = self.get_export_form(workspace_choices=workspace_choices)

                if not workspace_choices:
                    error = _('No RADAR workspaces are available for this account.')

        return render(self.request, 'plugins/exports_radar.html', {
            'form': form,
            'error': error
        }, status=200)

    def submit_export_form(self):
        if not self.get_from_session(self.request, 'access_token'):
            return self.render_credentials_form(
                error=_('Your RADAR login has expired. Please log in again.')
            )

        form = self.get_export_form(data=self.request.POST)
        if not form.is_valid():
            return self.render_export_form(form)

        candidate = self.get_selected_candidate(form)
        if candidate is None:
            return self.render_export_form(form)
        service = self.get_service()
        prepared = service.compute_payload(candidate, self.request.user.email)
        client = self.client
        try:
            data = client.create_dataset(
                self.get_from_session(self.request, 'access_token'),
                form.cleaned_data['workspace'],
                prepared.payload,
            )
        except (requests.RequestException, RadarProtocolError) as error:
            response = getattr(error, 'response', None)
            message = self.get_client_error_message(error, stage='export')
            if response is not None and response.status_code == 401:
                self.pop_from_session(self.request, 'access_token')
                return self.render_credentials_form(error=message)
            return self.render_export_form(form, error=message)

        radar_url = dataset_page_url(client.radar_url, data['id'], self.request.LANGUAGE_CODE)
        stored = True
        try:
            service.store_result(candidate, data['id'], radar_url)
        except ExportStoreError:
            logger.warning('Could not store confirmed RADAR dataset %s', data['id'])
            stored = False
        self.clear_session(self.request)
        return self.render_export_result(self.request, data['id'], radar_url, stored=stored)

    @property
    def client(self):
        return RadarClient(self.radar_url, self.client_id, self.client_secret, self.redirect_url, self.request_timeout)

    @property
    def redirect_url(self):
        redirect_uri = urlsplit(settings.RADAR_PROVIDER['redirect_uri'])
        return urlunsplit((redirect_uri.scheme, redirect_uri.netloc, '/', '', ''))


class RadarProjectCredentialsExportProvider(RadarCredentialsExportProvider):
    mapping = PROJECT_MAPPING


class RadarTemplateFrameworkCredentialsExportProvider(RadarCredentialsExportProvider):
    mapping = TEMPLATE_FRAMEWORK_MAPPING
