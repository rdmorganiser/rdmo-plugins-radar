"""Real RDMO values for mapper tests and canonical inputs for workflow tests."""
from rdmo.domain.models import Attribute
from rdmo.projects.models import Project, Value

from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.metadata.types import Agent, Identifier, RadarMetadata, Resource, Rights, SubjectArea


def add_answer(project, path, text, **coordinates):
    attribute = Attribute.objects.filter(path=path).first()
    if attribute is None:
        parent_path, _, key = path.rpartition('/')
        parent = None
        if parent_path:
            parent = add_attribute(parent_path)
        attribute = Attribute.objects.create(key=key, parent=parent, uri_prefix='https://rdmorganiser.github.io/terms')
    return Value.objects.create(project=project, attribute=attribute, text=text, **coordinates)


def add_attribute(path):
    attribute = Attribute.objects.filter(path=path).first()
    if attribute is None:
        parent_path, _, key = path.rpartition('/')
        parent = add_attribute(parent_path) if parent_path else None
        attribute = Attribute.objects.create(key=key, parent=parent, uri_prefix='https://rdmorganiser.github.io/terms')
    return attribute


def make_export(values=None):
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = Project.objects.create(title='Project')
    for path, text in (values or {}).items():
        add_answer(export.project, path, text)
    return export


def complete_metadata(**overrides):
    values = {
        'identifier': Identifier('10.1234/example', 'DOI'),
        'creators': [Agent('Doe, Jane')],
        'title': 'Dataset',
        'publishers': [Agent('Example Repository')],
        'production_year': '2026',
        'language': 'eng',
        'subject_areas': [SubjectArea('Chemistry')],
        'resource': Resource('Research data', 'Dataset'),
        'rights': Rights('CC BY 4.0 Attribution'),
        'rights_holders': [Agent('Example University')],
        'version': '1.0',
    }
    values.update(overrides)
    return RadarMetadata(**values)
