"""Software names and versions remain associated through their answer groups."""
from dataclasses import replace
from functools import partial

import pytest

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Value
from rdmo.questions.models import Catalog, CatalogSection, Section

from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import get_radar_validation_errors
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING
from rdmo_radar.mappings.template_framework.fields import TF_FIELDS
from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.fields import Source, read_software
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.types import Software
from rdmo_radar.metadata.xml import to_xml_payload

from .helpers import add_answer, complete_metadata
from .test_value_scopes import add_page, add_question, add_questionset

NAME = 'https://custom.test/domain/tools/name'
VERSION = 'https://custom.test/domain/tools/version'


def software_context(entries):
    values = {}
    for path, text, coordinates in entries:
        value = Value(attribute=Attribute(uri=path, path=path.rsplit('/', 1)[-1]), text=text, **coordinates)
        values.setdefault(path, []).append(value)
    return ProjectReadContext(values, {}, provenance=[])


def read_details(context, **kwargs):
    return read_software(context, source=Source(NAME), version_source=VERSION,
                         software_type='Resource Viewing', target='software', **kwargs)


def test_software_versions_follow_complete_group_coordinates_and_reach_both_outputs():
    context = software_context([
        (NAME, ' Viewer ', {'set_prefix': '2', 'set_index': 3}),
        (VERSION, ' 1.2 ', {'set_prefix': '2', 'set_index': 3}),
        (NAME, 'Analyser', {'set_prefix': '20', 'set_index': 3}),
        (VERSION, '4.5', {'set_prefix': '20', 'set_index': 3}),
        (VERSION, 'Orphan version', {'set_prefix': '2', 'set_index': 8}),
    ])
    fields = replace(TF_FIELDS, readers={**TF_FIELDS.readers, 'software': partial(
        read_software, source=Source(NAME), version_source=VERSION, software_type='Resource Viewing',
    )})
    result = compute_metadata(context, fields=fields)

    assert result.metadata.software == [Software('Viewer', 'Resource Viewing', '1.2'),
                                        Software('Analyser', 'Resource Viewing', '4.5')]
    assert not result.issues
    versions = [attempt for attempt in result.provenance if attempt.field.endswith('.version')]
    assert [attempt.value for attempt in versions] == ['1.2', '4.5']
    assert [attempt.sources[0].reference for attempt in versions] == [VERSION, VERSION]
    metadata = complete_metadata(software=result.metadata.software)
    xml = RadarExportRenderer().render(to_xml_payload(metadata))
    assert get_radar_validation_errors(xml) == ()
    api = to_api_payload(metadata)['software']['softwareType']
    assert [entry['softwareName'][0]['softwareVersion'] for entry in api] == ['1.2', '4.5']


@pytest.mark.parametrize('versions', [[], [''], ['1.0', '2.0']])
def test_missing_empty_or_conflicting_versions_preserve_the_software_name(versions):
    context = software_context([(NAME, 'Viewer', {})] + [
        (VERSION, version, {'collection_index': index}) for index, version in enumerate(versions)
    ])

    assert read_details(context) == [Software('Viewer', 'Resource Viewing')]
    assert any('Software version is unavailable' in issue.reason for issue in context.issues)


def test_one_version_is_not_assigned_to_multiple_names_in_a_group():
    context = software_context([
        (NAME, 'Viewer', {}), (NAME, 'Analyser', {'collection_index': 1}), (VERSION, '1.0', {}),
    ])

    assert read_details(context) == [Software('Viewer', 'Resource Viewing'), Software('Analyser', 'Resource Viewing')]
    assert any('multiple software names' in issue.reason for issue in context.issues)


def test_option_answers_do_not_become_plain_software_names():
    context = software_context([(NAME, 'Not a name', {}), (VERSION, '1.0', {})])
    context.get_values(NAME)[0].option = Option(uri='https://custom.test/options/no', uri_path='no')

    assert read_details(context) == []


def test_requirement_reader_can_use_a_version_without_a_dedicated_name_attribute():
    option = Option(uri='https://custom.test/options/required', uri_path='required')
    context = software_context([(NAME, 'Viewer', {}), (VERSION, '1.0', {})])
    context.get_values(NAME)[0].option = option

    assert read_details(context, option_map={option.uri: True}) == [Software('Viewer', 'Resource Viewing', '1.0')]
    assert context.issues == []


def test_no_version_source_preserves_existing_draft_behavior():
    context = software_context([(NAME, 'Viewer 1.2', {}), (VERSION, 'Unconfigured', {})])

    assert read_software(context, source=Source(NAME), target='software') == [Software('Viewer 1.2')]
    assert any('Software version is unavailable' in issue.reason for issue in context.issues)


def test_catalog_software_versions_follow_nested_groups_and_dataset_scope(db):
    catalog = Catalog.objects.create(uri_prefix='https://custom.test', uri_path='tools')
    section = Section.objects.create(uri_prefix='https://custom.test', uri_path='tools')
    CatalogSection.objects.create(catalog=catalog, section=section)
    project = Project.objects.create(title='Software groups', catalog=catalog)
    name_path, version_path = 'tools/name', 'tools/version'
    page = add_page(project, 'project/dataset/id', collection=True)
    tools = add_questionset(page, name_path, collection=True)
    details = add_questionset(tools)
    add_question(details, version_path)
    unrelated = add_questionset(page, 'unrelated/tool', collection=True)
    add_question(unrelated, version_path)
    for dataset in (2, 20):
        add_answer(project, 'project/dataset/id', f'Dataset {dataset}', set_index=dataset)
        for index, name in ((3, 'Viewer'), (7, 'Analyser')):
            add_answer(project, name_path, f'{name} {dataset}', set_prefix=str(dataset), set_index=index)
            add_answer(project, version_path, f'{dataset}.{index}', set_prefix=f'{dataset}|{index}')
            add_answer(project, version_path, 'Unrelated version', set_prefix=str(dataset), set_index=index)

    reader = TEMPLATE_FRAMEWORK_MAPPING.build_reader(project)
    for dataset in (2, 20):
        context = reader(dataset)
        software = read_software(context, source=Source(name_path), version_source=version_path,
                                 software_type='Resource Viewing', target='software')
        assert software == [Software(f'Viewer {dataset}', 'Resource Viewing', f'{dataset}.3'),
                            Software(f'Analyser {dataset}', 'Resource Viewing', f'{dataset}.7')]
        assert not context.issues
