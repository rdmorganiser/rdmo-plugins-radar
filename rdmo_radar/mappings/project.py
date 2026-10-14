"""Export one conservative metadata record for an RDMO project."""
from ..metadata.rdmo import RDMOReadContext
from ..metadata.types import MappingResult, RadarMetadata
from ..metadata.values import fetch_catalog_placements, fetch_project_values, prepare_read_data
from . import ExportDataset, RadarMapping


def build_reader(project, snapshot=None):
    attribute_values_map = fetch_project_values(project, snapshot)
    attribute_placements_map = fetch_catalog_placements(project.catalog)
    prepared = prepare_read_data(attribute_values_map, attribute_placements_map)

    def read(dataset):
        return RDMOReadContext(
            attribute_values_map, attribute_placements_map, scope='project', prepared=prepared, project=project
        )

    return read


def get_datasets(project, reader):
    return [ExportDataset('project', project.title, {'mode': 'project'})]


def compute_metadata(context):
    return MappingResult(RadarMetadata(title=context.project.title), tuple(context.issues))


PROJECT_MAPPING = RadarMapping(get_datasets, build_reader, compute_metadata)
