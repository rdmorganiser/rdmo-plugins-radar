import logging
import mimetypes

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from rdmo.core.xml import get_ns_map, read_xml_file
from rdmo.projects.imports import Import

from rdmo_radar.exceptions import UnsupportedImportMapping
from rdmo_radar.factories import build_import_service
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING

logger = logging.getLogger(__name__)


class RadarImport(Import):
    mapping = TEMPLATE_FRAMEWORK_MAPPING

    def check(self):
        file_type, _encoding = mimetypes.guess_type(self.file_name)
        if file_type == 'application/xml':
            self.root = read_xml_file(self.file_name)
            if self.root is not None:
                namespace = get_ns_map(self.root)
                return self.root.tag == '{{{ns0}}}radarDataset'.format(**namespace)
        return False

    def process(self):
        if self.current_project is None:
            raise ValidationError(_(
                'RADAR files can only be imported into existing projects. Please create a project first.'
            ))
        self.catalog = self.current_project.catalog
        try:
            self.mapping_issues = build_import_service(self, profile=self.mapping).process(self.root)
        except UnsupportedImportMapping as error:
            raise ValidationError(_('The selected RADAR mapping does not support import.')) from error
        for issue in self.mapping_issues:
            logger.warning('RADAR import mapping issue: %s', issue)
        request = getattr(self, 'request', None)
        if request is not None and hasattr(request, '_messages') and self.mapping_issues:
            messages.warning(request, _(
                'Some RADAR metadata could not be mapped to confirmed RDMO fields. See the server log for details.'
            ))


class RadarTemplateFrameworkImport(RadarImport):
    mapping = TEMPLATE_FRAMEWORK_MAPPING
