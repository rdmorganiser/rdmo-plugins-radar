from urllib.parse import urlsplit, urlunsplit

from django import forms
from django.conf import settings
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from .client import RadarAuthenticationError, RadarClient, RadarClientError
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
            access_token = self.client.authenticate(
                form.cleaned_data['username'], form.cleaned_data['password']
            )
        except RadarClientError as error:
            form.add_error(None, self.get_client_error_message(error))
            return self.render_credentials_form(form)

        self.store_in_session(self.request, 'access_token', access_token)
        return redirect('project_export', self.project.id, self.key)

    def render_export_form(self, form=None, error=None):
        if form is None:
            try:
                workspace_choices = self.client.get_workspaces(
                    self.get_from_session(self.request, 'access_token')
                )
            except RadarAuthenticationError as error:
                self.pop_from_session(self.request, 'access_token')
                return self.render_credentials_form(error=self.get_client_error_message(error))
            except RadarClientError as client_error:
                form = self.get_export_form()
                error = self.get_client_error_message(client_error)
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

        self.store_in_session(self.request, 'set_index', form.cleaned_data['dataset'])

        try:
            data = self.client.create_dataset(
                self.get_from_session(self.request, 'access_token'),
                form.cleaned_data['workspace'],
                self.get_post_data(form.cleaned_data['dataset']),
            )
        except RadarAuthenticationError as error:
            self.pop_from_session(self.request, 'access_token')
            return self.render_credentials_form(error=self.get_client_error_message(error))
        except RadarClientError as error:
            return self.render_export_form(form, error=self.get_client_error_message(error))

        result = self.complete_export(self.request, data['id'])
        self.clear_session(self.request)
        return result

    @property
    def client(self):
        return RadarClient(self.radar_url, self.client_id, self.client_secret, self.redirect_url, self.request_timeout)

    @property
    def token_url(self):
        return self.client.token_url

    @property
    def redirect_url(self):
        redirect_uri = urlsplit(settings.RADAR_PROVIDER['redirect_uri'])
        return urlunsplit((redirect_uri.scheme, redirect_uri.netloc, '/', '', ''))
