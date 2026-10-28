"""Export one conservative metadata record for an RDMO project."""
from ..metadata.read_context import ProjectReadContext
from ..metadata.types import MappingResult, MappingSource, RadarMetadata
from . import ExportDataset, RadarMapping
from .common.readers import prepare_project_read


def build_reader(project, snapshot=None):
    attribute_values_map, attribute_placements_map, prepared = prepare_project_read(project, snapshot)

    def read(dataset):
        return ProjectReadContext(
            attribute_values_map, attribute_placements_map, scope='project', prepared=prepared, project=project
        )

    return read


def get_datasets(project, reader):
    return [ExportDataset('project', project.title, {'mode': 'project'})]


def compute_metadata(context):
    context.record_mapping('title', sources=(MappingSource('Project.title', context.project.title),),
                           value=context.project.title, outcome='mapped' if context.project.title else 'empty',
                           reason='RDMO project title')
    return MappingResult(RadarMetadata(title=context.project.title), tuple(context.issues))


PROJECT_MAPPING = RadarMapping(get_datasets, build_reader, compute_metadata)
