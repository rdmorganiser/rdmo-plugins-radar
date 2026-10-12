import logging
import zipfile

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from rdmo.projects.exports import Export

from rdmo_radar.exceptions import XmlExportError
from rdmo_radar.factories import build_xml_export_service
from rdmo_radar.mappings import validate_candidates
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING

from .validation import REQUIRED_FIELD_LABELS

logger = logging.getLogger(__name__)


class RadarExport(Export):
    mapping = TEMPLATE_FRAMEWORK_MAPPING

    def get_service(self):
        if self.project is None and self.snapshot is not None:
            self.project = self.snapshot.project
        key = (id(self.project), self.snapshot, self.project.catalog_id, id(self.mapping))
        if getattr(self, '_service_key', None) != key:
            self._service = build_xml_export_service(self.project, snapshot=self.snapshot, profile=self.mapping)
            self._service_key = key
        return self._service

    def get_dataset_indices(self):
        """Legacy TF convenience; workflows use candidates with complete scope instead."""
        return sorted({candidate.scope['set_index'] for candidate in self.get_candidates()})

    def get_candidates(self):
        service = self.get_service()
        if getattr(self, '_candidate_service', None) is not service:
            self._candidates = validate_candidates(self.mapping.get_datasets(self.project, service.reader))
            self._candidate_service = service
        return self._candidates

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
        files = self.get_service().compute_files(self.get_candidates())
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


class RadarProjectExport(RadarExport):
    mapping = PROJECT_MAPPING


class RadarTemplateFrameworkExport(RadarExport):
    mapping = TEMPLATE_FRAMEWORK_MAPPING
