import logging
import zipfile

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from rdmo.projects.exports import Export

from rdmo_radar.exceptions import XmlExportError
from rdmo_radar.factories import build_xml_export_service
from rdmo_radar.mappings import validate_datasets
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING

from .previews import compute_mapping_preview, compute_source_answers
from .validation import REQUIRED_FIELD_LABELS

logger = logging.getLogger(__name__)


class RadarExport(Export):
    mapping = TEMPLATE_FRAMEWORK_MAPPING

    def get_service(self):
        if self.project is None and self.snapshot is not None:
            self.project = self.snapshot.project
        collect_mapping = (
            getattr(settings, 'RADAR_PREVIEW_MAPPING', False)
            or getattr(settings, 'RADAR_PREVIEW_SOURCE_ANSWERS', False)
        ) and not self._downloading()
        key = (id(self.project), self.snapshot, self.project.catalog_id, id(self.mapping), collect_mapping)
        if getattr(self, '_service_key', None) != key:
            self._service = build_xml_export_service(
                self.project, snapshot=self.snapshot, profile=self.mapping, collect_mapping=collect_mapping,
            )
            self._service_key = key
        return self._service

    def get_datasets(self):
        """Return the datasets that this mapping can export from the RDMO project."""
        service = self.get_service()
        if getattr(self, '_dataset_service', None) is not service:
            self._datasets = validate_datasets(self.mapping.get_datasets(self.project, service.reader))
            self._dataset_service = service
        return self._datasets

    def render(self):
        try:
            files = self.prepare_files()
        except XmlExportError as error:
            logger.exception('Could not generate RADAR XML file %s', error.file_name)
            message = _('RADAR XML export could not generate "%(file_name)s".') % {'file_name': error.file_name}
            return HttpResponseBadRequest(message, content_type='text/plain')

        preview_flags = {
            'preview_payload': getattr(settings, 'RADAR_PREVIEW_PAYLOAD', False),
            'preview_source_answers': getattr(settings, 'RADAR_PREVIEW_SOURCE_ANSWERS', False),
            'preview_mapping': getattr(settings, 'RADAR_PREVIEW_MAPPING', False),
        }
        has_warnings = any(file['has_warnings'] for file in files)
        if (has_warnings or any(preview_flags.values())) and not self._downloading():
            return render(self.request, 'plugins/exports_radar_xml_validation.html', {
                'project': self.project,
                'project_url': self.project.get_absolute_url(),
                'files': files,
                'has_warnings': has_warnings,
                'snapshot': self.snapshot,
                'debug_mode': getattr(settings, 'RADAR_DEBUG', False),
                **preview_flags,
            })

        return self.render_zip(files)

    def prepare_files(self):
        datasets = self.get_datasets()
        files = self.get_service().compute_files(datasets)
        result = []
        for dataset, file in zip(datasets, files, strict=True):
            prepared = {
                'dataset': dataset,
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
                'mapping_preview': compute_mapping_preview(file.provenance),
                'source_values': None, 'source_answers': None, 'source_error': None,
                'payload_preview': None, 'payload_error': None,
            }
            if not self._downloading():
                if getattr(settings, 'RADAR_PREVIEW_PAYLOAD', False):
                    try:
                        prepared['payload_preview'] = file.xml_data.decode('utf-8')
                    except Exception as error:
                        logger.warning('Could not prepare RADAR XML preview: error_type=%s', type(error).__name__)
                        prepared['payload_error'] = _('The XML preview could not be prepared. Please contact support.')
                if getattr(settings, 'RADAR_PREVIEW_SOURCE_ANSWERS', False):
                    try:
                        prepared['source_values'] = self.get_source_values(dataset)
                        prepared['source_answers'] = compute_source_answers(
                            prepared['source_values'], prepared['mapping_preview'],
                        )
                    except Exception as error:
                        logger.warning('Could not prepare RADAR source answers: error_type=%s', type(error).__name__)
                        prepared['source_error'] = _(
                            'The source answers could not be prepared. Please contact support.'
                        )
            result.append(prepared)
        return result

    def get_source_values(self, dataset):
        return self.get_service().reader(dataset).get_scope_values()

    def _downloading(self):
        return getattr(getattr(self, 'request', None), 'GET', {}).get('download') == '1'

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
