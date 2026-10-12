"""Export one conservative metadata record for an RDMO project."""
from ..metadata.rdmo import RDMOReadContext
from ..metadata.types import MappingResult, RadarMetadata
from ..metadata.values import fetch_catalog_placements, fetch_project_values, prepare_read_data
from . import ExportCandidate, RadarMapping


def build_reader(project, snapshot=None):
    values = fetch_project_values(project, snapshot)
    placements = fetch_catalog_placements(project.catalog)
    prepared = prepare_read_data(values, placements)

    def read(candidate):
        return RDMOReadContext(values, placements, scope='project', prepared=prepared, project=project)

    return read


def get_datasets(project, reader):
    return [ExportCandidate('project', project.title, {'mode': 'project'})]


def compute_metadata(context):
    return MappingResult(RadarMetadata(title=context.project.title), tuple(context.issues))


PROJECT_MAPPING = RadarMapping(get_datasets, build_reader, compute_metadata)
