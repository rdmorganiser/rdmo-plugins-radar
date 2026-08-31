from urllib.parse import urlsplit, urlunsplit

from django import forms
from django.conf import settings
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

import requests

from .providers import RadarExportProviderBase


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
            response = requests.post(
                self.token_url,
                json={
                    'clientId': self.client_id,
                    'clientSecret': self.client_secret,
                    'userName': form.cleaned_data['username'],
                    'userPassword': form.cleaned_data['password'],
                    'redirectUrl': self.redirect_url
                },
                timeout=self.request_timeout
            )
            response.raise_for_status()
            access_token = response.json().get('access_token')
        except (requests.RequestException, AttributeError, ValueError):
            access_token = None

        if not access_token:
            form.add_error(None, _('RADAR login failed. Please check your credentials and try again.'))
            return self.render_credentials_form(form)

        self.store_in_session(self.request, 'access_token', access_token)
        return redirect('project_export', self.project.id, self.key)

    def render_export_form(self, form=None, error=None):
        if form is None:
            try:
                response = requests.get(
                    self.get_get_url(),
                    headers=self.get_authorization_headers(self.get_from_session(self.request, 'access_token')),
                    timeout=self.request_timeout
                )
                response.raise_for_status()
                workspace_choices = self.get_workspace_choices(response)
            except (requests.RequestException, AttributeError, ValueError):
                self.clear_session(self.request)
                return self.render_credentials_form(
                    error=_('RADAR workspaces could not be retrieved. Please log in and try again.')
                )

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

        self.store_in_session(self.request, 'set_index', form.cleaned_data['dataset'])

        try:
            response = requests.post(
                self.get_post_url(form.cleaned_data['workspace']),
                json=self.get_post_data(form.cleaned_data['dataset']),
                headers=self.get_authorization_headers(self.get_from_session(self.request, 'access_token')),
                timeout=self.request_timeout
            )
            response.raise_for_status()
            result = self.post_success(self.request, response)
        except (requests.RequestException, AttributeError, ValueError):
            result = self.render_credentials_form(
                error=_('The dataset could not be exported to RADAR. Please log in and try again.')
            )
        finally:
            self.clear_session(self.request)

        return result

    @property
    def token_url(self):
        return f'{self.radar_url}/radar/api/tokens'

    @property
    def redirect_url(self):
        redirect_uri = urlsplit(settings.RADAR_PROVIDER['redirect_uri'])
        return urlunsplit((redirect_uri.scheme, redirect_uri.netloc, '/', '', ''))
