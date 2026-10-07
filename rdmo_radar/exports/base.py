"""Project metadata behavior shared by XML and direct RADAR exports."""

from django.utils.translation import gettext_lazy as _

from rdmo.projects.exports import Export

from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.rdmo import RDMOReadContext
from rdmo_radar.metadata.values import get_answer_index

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


class RadarProjectExportBase(Export):
    def compute_metadata(self, set_index):
        return compute_metadata(self, int(set_index))

    def get_dataset_title(self, set_index):
        context = RDMOReadContext(self, set_index=int(set_index))
        return context.get_text('project/dataset/title') or context.get_text('project/dataset/id')

    def get_dataset_indices(self):
        return get_answer_index(self).dataset_indices()
