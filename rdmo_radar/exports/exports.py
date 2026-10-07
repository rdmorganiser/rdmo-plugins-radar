import logging
import re
import zipfile
from dataclasses import dataclass

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from rdmo.core.exports import prettify_xml
from rdmo.projects.exports import Export

from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.constants import XMLVocabulary
from rdmo_radar.metadata.rdmo import RDMOReadContext
from rdmo_radar.metadata.types import MappingIssue
from rdmo_radar.metadata.values import get_answer_index
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
    mapping_issues: tuple[MappingIssue, ...] = ()

    @property
    def has_warnings(self):
        return bool(self.missing_fields or self.validation_errors or self.mapping_issues)


class RadarExport(XMLVocabulary, Export):
    def compute_metadata(self, set_index):
        return compute_metadata(self, set_index)

    def get_dataset(self, set_index):
        metadata = self.compute_metadata(set_index)
        self.mapping_issues = metadata.mapping_issues
        return to_xml_payload(metadata)

    def get_dataset_title(self, set_index):
        context = RDMOReadContext(self, set_index=int(set_index))
        return context.get_text('project/dataset/title') or context.get_text('project/dataset/id')

    def get_dataset_indices(self):
        """Discover datasets from collection labels and explicit titles."""
        index = get_answer_index(self)
        if index is not None:
            return index.dataset_indices()
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
        names = set()
        for set_index in self.get_dataset_indices():
            title = self.get_dataset_title(set_index) or str(set_index + 1)
            stem = re.sub(r'[/\\\x00-\x1f\x7f]', '_', title).strip(' .')[:180] or str(set_index + 1)
            file_name = f'{stem}.xml'
            suffix = 2
            while file_name.casefold() in names:
                file_name = f'{stem}-{suffix}.xml'
                suffix += 1
            names.add(file_name.casefold())
            try:
                self.mapping_issues = []
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
                mapping_issues=tuple(self.mapping_issues),
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
