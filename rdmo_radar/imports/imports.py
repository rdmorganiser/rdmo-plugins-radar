import logging
import mimetypes

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from rdmo.core.xml import get_ns_map, read_xml_file
from rdmo.projects.imports import Import

from rdmo_radar.metadata.importer import write_metadata
from rdmo_radar.metadata.xml import parse_xml

logger = logging.getLogger(__name__)


class RadarImport(Import):
    def check(self):
        file_type, _encoding = mimetypes.guess_type(self.file_name)
        if file_type == 'application/xml':
            self.root = read_xml_file(self.file_name)
            if self.root:
                namespace = get_ns_map(self.root)
                return self.root.tag == '{{{ns0}}}radarDataset'.format(**namespace)
        return False

    def process(self):
        if self.current_project is None:
            raise ValidationError(_(
                'RADAR files can only be imported into existing projects. Please create a project first.'
            ))
        self.catalog = self.current_project.catalog
        metadata = parse_xml(self.root)
        self.mapping_issues = write_metadata(self, metadata, self.get_next_dataset_index())
        for issue in self.mapping_issues:
            logger.warning('RADAR import mapping issue: %s', issue)
        request = getattr(self, 'request', None)
        if request is not None and hasattr(request, '_messages') and self.mapping_issues:
            messages.warning(request, _(
                'Some RADAR metadata could not be mapped to confirmed RDMO fields. See the server log for details.'
            ))

    def get_next_dataset_index(self):
        current_datasets = self.current_project.values.filter(
            snapshot=None,
            attribute__path='project/dataset/title',
        )
        return max((value.set_index for value in current_datasets), default=-1) + 1
