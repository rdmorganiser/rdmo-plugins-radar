import logging
import zipfile
from dataclasses import dataclass

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from rdmo.core.exports import prettify_xml
from rdmo.projects.exports import Export

from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.constants import XMLVocabulary
from rdmo_radar.metadata.xml import missing_required_fields, to_xml_payload

from .renderers import RadarExportRenderer
from .validation import get_radar_validation_errors

logger = logging.getLogger(__name__)

REQUIRED_FIELD_LABELS = {
    'identifier': _('Identifier'),
    'identifier.identifierType': _('Identifier type'),
    'creators.creator': _('Creator'),
    'title': _('Title'),
    'publishers.publisher': _('Publisher'),
    'productionYear': _('Production year'),
    'subjectAreas.subjectArea': _('Subject area'),
    'resource.value': _('Resource description'),
    'resource.resourceType': _('Resource type'),
    'rights.controlledRights': _('Rights'),
    'rightsHolders.rightsHolder': _('Rights holder'),
}


@dataclass(frozen=True, slots=True)
class MissingMetadataField:
    path: str
    label: str


@dataclass(frozen=True, slots=True)
class RadarXmlExportFile:
    file_name: str
    xml_data: bytes
    missing_fields: tuple[MissingMetadataField, ...]
    validation_errors: tuple[str, ...]

    @property
    def has_warnings(self):
        return bool(self.missing_fields or self.validation_errors)


class RadarExport(XMLVocabulary, Export):
    def compute_metadata(self, set_index):
        return compute_metadata(self, set_index)

    def get_dataset(self, set_index):
        return to_xml_payload(self.compute_metadata(set_index))

    def get_dataset_indices(self):
        """Return every dataset set, including pre-migration sets with only an id marker."""
        indices = set()
        for attribute in ('project/dataset/title', 'project/dataset/id'):
            indices.update(value.set_index for value in self.get_set(attribute))
        return sorted(indices)

    def render(self):
        try:
            files = self.prepare_files()
        except RadarXmlGenerationError as error:
            return HttpResponseBadRequest(str(error), content_type='text/plain')

        if any(file.has_warnings for file in files) and self.request.GET.get('download') != '1':
            return render(self.request, 'plugins/exports_radar_xml_validation.html', {
                'project': self.project,
                'project_url': self.project.get_absolute_url(),
                'files': files,
            })

        return self.render_zip(files)

    def prepare_files(self):
        files = []
        for set_index in self.get_dataset_indices():
            file_name = '{}.xml'.format(
                self.get_text('project/dataset/data_publication_pid', set_index=set_index)
                or self.get_text('project/dataset/title', set_index=set_index)
                or str(set_index + 1)
            )
            try:
                dataset = self.get_dataset(set_index)
                xmldata = prettify_xml(RadarExportRenderer().render(dataset))
            except Exception as error:
                logger.exception('Could not generate RADAR XML file %s', file_name)
                raise RadarXmlGenerationError(
                    _('RADAR XML export could not generate "%(file_name)s".') % {'file_name': file_name}
                ) from error

            missing_fields = tuple(
                MissingMetadataField(path, REQUIRED_FIELD_LABELS.get(path, path))
                for path in missing_required_fields(dataset)
            )
            try:
                validation_errors = get_radar_validation_errors(xmldata)
            except Exception:
                logger.exception('Could not validate RADAR XML file %s', file_name)
                validation_errors = (_('The RDDM schema validation could not be completed.'),)

            files.append(RadarXmlExportFile(
                file_name=file_name,
                xml_data=xmldata,
                missing_fields=missing_fields,
                validation_errors=validation_errors,
            ))
        return files

    def render_zip(self, files):
        response = HttpResponse(content_type='application/zip')
        response['Content-Disposition'] = f'filename="{self.project.title}.zip"'
        with zipfile.ZipFile(response, 'w') as zip_file:
            for file in files:
                zip_file.writestr(file.file_name, file.xml_data)
        return response


class RadarXmlGenerationError(Exception):
    pass
