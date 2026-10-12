"""Real RDMO values for mapper tests and canonical inputs for workflow tests."""
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Value

from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.mappings import ExportCandidate
from rdmo_radar.metadata.rdmo import TERMS_PREFIX, RDMOReadContext
from rdmo_radar.metadata.types import Agent, Identifier, RadarMetadata, Resource, Rights, SubjectArea
from rdmo_radar.services import RadarExportService


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


def add_namespaced_attribute(path, uri_prefix):
    """Create a separate attribute tree without path-only fixture resolution."""
    parent_path, _, key = path.rpartition('/')
    parent = add_namespaced_attribute(parent_path, uri_prefix) if parent_path else None
    return Attribute.objects.get_or_create(key=key, parent=parent, uri_prefix=uri_prefix)[0]


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


XML_DIRECTORY = Path(__file__).parent / 'xml'
URI = '{http://purl.org/dc/elements/1.1/}uri'


def make_read_context():
    values = {}
    for path, text, prefix in (
        ('project/dataset/title', 'Dataset', ''),
        ('project/dataset/description', 'Description', ''),
        ('project/dataset/creator/name', 'Creator', '0'),
        ('project/partner/name', 'Partner', ''),
        ('project/funder/name', 'Funder', ''),
    ):
        values[path] = [Value(attribute=Attribute(path=path), text=text, set_prefix=prefix)]
    return RDMOReadContext(values, placements={})


def make_import():
    attributes = {path: Attribute(path=path) for path in (
        'project/dataset/title', 'project/dataset/description', 'project/research_question/keywords',
        'project/dataset/creator/name', 'project/partner/name',
        'project/funder/id', 'project/funder/name', 'project/funder/grant_nr',
    )}
    return SimpleNamespace(
        values=[], current_project=None,
        get_attribute=lambda uri: attributes.get(uri.removeprefix(TERMS_PREFIX)),
        get_option=lambda uri: None,
    )


def make_prototype(catalog_id):
    root = ElementTree.parse(XML_DIRECTORY / 'RADAR Plugin Testprojekt.xml').getroot()
    project = Project.objects.create(title=root.findtext('title'), catalog_id=catalog_id)
    attributes = {attribute.uri: attribute for attribute in Attribute.objects.all()}
    options = {option.uri: option for option in Option.objects.all()}
    Value.objects.bulk_create([
        Value(
            project=project,
            attribute=attributes[node.find('attribute').get(URI)],
            option=options.get(node.find('option').get(URI)),
            text=node.findtext('text') or '',
            external_id=node.findtext('external_id') or '',
            value_type=node.findtext('value_type'),
            created=node.findtext('created'),
            updated=node.findtext('updated'),
            set_prefix=node.findtext('set_prefix') or '',
            set_index=int(node.findtext('set_index')),
            collection_index=int(node.findtext('collection_index')),
        ) for node in root.findall('./values/value')
    ])
    return project


def export_for(project, cls=RadarExport):
    export = cls('radar', 'RADAR', f'rdmo_radar.exports.{cls.__name__}')
    export.project = project
    export.request = SimpleNamespace(session={}, user=SimpleNamespace(email='user@example.test'), LANGUAGE_CODE='en')
    return export



def read_metadata(export, set_index):
    service = export.get_service()
    return service.mapping(service.reader(int(set_index)))


def dataset_payload(export, set_index):
    service = export.get_service()
    if isinstance(service, RadarExportService):
        return service.compute_payload(set_index, export.request.user.email).payload['descriptiveMetadata']
    return service.serializer(read_metadata(export, set_index).metadata)


def dataset_title(export, set_index):
    context = export.get_service().reader(set_index)
    return context.get_text('project/dataset/title') or context.get_text('project/dataset/id')



def configure_service(export, reader=None):
    reader = reader if reader is not None else lambda selection: RDMOReadContext(
        {}, {}, set_index=selection.scope['set_index'] if isinstance(selection, ExportCandidate) else selection,
    )
    if isinstance(export, RadarExport):
        service = build_xml_export_service(None, reader=reader)
    else:
        service = build_export_service(None, reader=reader, writer=lambda *args: None)
    export.get_service = lambda: service
    return export
