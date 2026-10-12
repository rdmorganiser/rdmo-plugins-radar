import logging
import zipfile

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from rdmo.projects.exports import Export

from rdmo_radar.exceptions import XmlExportError
from rdmo_radar.factories import build_xml_export_service
from rdmo_radar.metadata.values import compute_dataset_indices

from .validation import REQUIRED_FIELD_LABELS

logger = logging.getLogger(__name__)


class RadarExport(Export):
    def get_service(self):
        if self.project is None and self.snapshot is not None:
            self.project = self.snapshot.project
        key = (id(self.project), self.snapshot, self.project.catalog_id)
        if getattr(self, '_service_key', None) != key:
            self._service = build_xml_export_service(self.project, snapshot=self.snapshot)
            self._service_key = key
        return self._service

    def get_dataset_indices(self):
        context = self.get_service().reader(0)
        return compute_dataset_indices(context.values, context.placements)

    def render(self):
        try:
            files = self.prepare_files()
        except XmlExportError as error:
            logger.exception('Could not generate RADAR XML file %s', error.file_name)
            message = _('RADAR XML export could not generate "%(file_name)s".') % {'file_name': error.file_name}
            return HttpResponseBadRequest(message, content_type='text/plain')

        if any(file['has_warnings'] for file in files) and self.request.GET.get('download') != '1':
            return render(self.request, 'plugins/exports_radar_xml_validation.html', {
                'project': self.project,
                'project_url': self.project.get_absolute_url(),
                'files': files,
            })

        return self.render_zip(files)

    def prepare_files(self):
        files = self.get_service().compute_files(self.get_dataset_indices())
        return [{
            'file_name': file.file_name,
            'xml_data': file.xml_data,
            'missing_fields': tuple(
                {'path': path, 'label': REQUIRED_FIELD_LABELS.get(path, path)} for path in file.missing_fields
            ),
            'validation_errors': file.validation_errors if not file.validation_failed else (
                _('The RDDM schema validation could not be completed.'),
            ),
            'mapping_issues': file.issues,
            'has_warnings': file.has_warnings,
        } for file in files]

    def render_zip(self, files):
        response = HttpResponse(content_type='application/zip')
        response['Content-Disposition'] = f'filename="{self.project.title}.zip"'
        with zipfile.ZipFile(response, 'w') as zip_file:
            for file in files:
                zip_file.writestr(file['file_name'], file['xml_data'])
        return response
