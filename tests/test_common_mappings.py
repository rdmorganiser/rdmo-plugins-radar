"""Shared definitions do not couple profile policies or operation state."""
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

from rdmo.projects.models import Project, Snapshot

from rdmo_radar.mappings import ExportDataset
from rdmo_radar.mappings.common import vocabulary as common_options
from rdmo_radar.mappings.legacy import LEGACY_MAPPING
from rdmo_radar.mappings.legacy import vocabulary as legacy_options
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING
from rdmo_radar.mappings.template_framework.crosswalks import PID_SYSTEM_OPTIONS
from rdmo_radar.mappings.template_framework.vocabulary import XMLVocabulary

from .helpers import add_answer


def test_tf_pid_crosswalk_covers_catalog_options_with_schema_valid_scheme_spellings():
    root_dir = Path(__file__).parents[1]
    catalog = ElementTree.parse(root_dir / 'tests/xml/dmp4nfdi_v2-0-0.xml').getroot()
    uri = '{http://purl.org/dc/elements/1.1/}uri'
    prefix = 'https://dmp.service.base4nfdi.de/terms/options/'
    option_set = next(e for e in catalog.findall('optionset') if e.get(uri) == prefix + 'pid_system')
    assert set(PID_SYSTEM_OPTIONS) == {e.get(uri) for e in option_set.findall('options/option')}
    assert len(PID_SYSTEM_OPTIONS) == 19
    schema = ElementTree.parse(root_dir / 'rdmo_radar/schemas/RadarTypes.xsd').getroot()
    ns = '{http://www.w3.org/2001/XMLSchema}'
    allowed = {e.get('value') for e in schema.findall(
        f"{ns}simpleType[@name='relatedIdentifierType']/{ns}restriction/{ns}enumeration"
    )}
    for option in catalog.findall('option'):
        key = option.get(uri)
        if key not in PID_SYSTEM_OPTIONS:
            continue
        scheme = PID_SYSTEM_OPTIONS[key]
        label = option.findtext("text[@lang='en']")
        if scheme is None:
            assert label == 'other'
        else:
            assert scheme in allowed
            assert scheme.casefold() == label.split()[0].casefold()


@pytest.mark.parametrize('common_name,legacy_name,tf_name', [
    ('IDENTIFIER_TYPE_OPTIONS', 'IDENTIFIER_TYPE_OPTIONS', 'identifier_type_options'),
    ('RELATED_IDENTIFIER_TYPE_OPTIONS', 'RELATED_IDENTIFIER_TYPE_OPTIONS', 'related_identifier_type_options'),
    ('LANGUAGE_OPTIONS', 'LANGUAGE_OPTIONS', 'language_options'),
    ('NAME_TYPE_OPTIONS', 'NAME_TYPE_OPTIONS', 'name_type_options'),
    ('CONTRIBUTOR_TYPE_OPTIONS', 'CONTRIBUTOR_TYPE_OPTIONS', 'contributor_type_options'),
    ('RESOURCE_TYPE_GENERAL_OPTIONS', 'RESOURCE_TYPE_OPTIONS', 'resource_type_general_options'),
    ('CONTROLLED_SUBJECT_AREA_OPTIONS', 'CONTROLLED_SUBJECT_AREA_OPTIONS', 'controlled_subject_area_options'),
    ('DATA_SOURCE_OPTIONS', 'DATA_SOURCE_OPTIONS', 'data_source_options'),
    ('CONTROLLED_RIGHTS_OPTIONS', 'CONTROLLED_RIGHTS_OPTIONS', 'controlled_rights_options'),
    ('RELATION_TYPE_OPTIONS', 'RELATION_TYPE_OPTIONS', 'relation_type_options'),
])
def test_shared_vocabulary_is_read_only_and_profile_copies_are_independent(
    monkeypatch, common_name, legacy_name, tf_name,
):
    common = getattr(common_options, common_name)
    legacy = getattr(legacy_options, legacy_name)
    template_framework = getattr(XMLVocabulary, tf_name)
    assert legacy == template_framework == common
    assert isinstance(legacy, dict)
    assert isinstance(template_framework, dict)
    assert legacy is not template_framework
    with pytest.raises(TypeError):
        common['local/choice'] = 'Local'
    monkeypatch.setitem(legacy, 'legacy/choice', 'Legacy')
    monkeypatch.setitem(template_framework, 'tf/choice', 'TF')
    assert 'legacy/choice' not in common
    assert 'legacy/choice' not in template_framework
    assert 'tf/choice' not in common
    assert 'tf/choice' not in legacy


@pytest.mark.parametrize('name', [
    'DESCRIPTION_TYPE_OPTIONS', 'NAME_IDENTIFIER_SCHEME_OPTIONS', 'FUNDER_IDENTIFIER_SCHEME_OPTIONS',
    'SOFTWARE_TYPE_OPTIONS',
])
def test_remaining_tf_vocabularies_are_copies_of_read_only_common_tables(monkeypatch, name):
    common = getattr(common_options, name)
    template_framework = getattr(XMLVocabulary, name.lower())
    assert template_framework == common
    with pytest.raises(TypeError):
        common['local/choice'] = 'Local'
    monkeypatch.setitem(template_framework, 'tf/choice', 'TF')
    assert 'tf/choice' not in common


def test_legacy_identifier_scheme_overrides_are_explicit_and_isolated(monkeypatch):
    expected = {
        **common_options.NAME_IDENTIFIER_SCHEME_OPTIONS,
        'name_identifier_scheme/insi': 'ISNI',
        'name_identifier_scheme/grid': 'GRID',
    }
    assert legacy_options.NAME_IDENTIFIER_SCHEME_OPTIONS == expected
    monkeypatch.setitem(legacy_options.NAME_IDENTIFIER_SCHEME_OPTIONS, 'legacy/choice', 'Legacy')
    assert 'legacy/choice' not in common_options.NAME_IDENTIFIER_SCHEME_OPTIONS
    assert 'legacy/choice' not in XMLVocabulary.name_identifier_scheme_options


def test_primary_identifier_types_are_read_only_with_a_profile_local_copy():
    assert isinstance(common_options.PRIMARY_IDENTIFIER_TYPES, frozenset)
    assert isinstance(XMLVocabulary.primary_identifier_types, set)
    assert XMLVocabulary.primary_identifier_types == common_options.PRIMARY_IDENTIFIER_TYPES


@pytest.mark.parametrize('name,schema_type', [
    ('PRIMARY_IDENTIFIER_TYPES', 'identifierType'),
    ('RELATED_IDENTIFIER_TYPE_OPTIONS', 'relatedIdentifierType'),
    ('NAME_IDENTIFIER_SCHEME_OPTIONS', 'nameIdentifierScheme'),
    ('FUNDER_IDENTIFIER_SCHEME_OPTIONS', 'funderIdentifierType'),
])
def test_identifier_vocabularies_match_their_distinct_radar_schema_types(name, schema_type):
    root = ElementTree.parse(Path(__file__).parents[1] / 'rdmo_radar/schemas/RadarTypes.xsd').getroot()
    ns = '{http://www.w3.org/2001/XMLSchema}'
    restriction = root.find(f"{ns}simpleType[@name='{schema_type}']/{ns}restriction")
    allowed = {item.get('value') for item in restriction.findall(f'{ns}enumeration')}
    vocabulary = getattr(common_options, name)
    values = vocabulary if name == 'PRIMARY_IDENTIFIER_TYPES' else vocabulary.values()
    assert set(values) == allowed


def test_common_vocabulary_import_does_not_load_django_or_reader_code():
    code = """
import sys
from rdmo_radar.mappings.common.vocabulary import NAME_TYPE_OPTIONS
assert NAME_TYPE_OPTIONS['name_type/personal'] == 'Personal'
assert 'rdmo_radar.mappings.common.readers' not in sys.modules
assert 'django' not in sys.modules
"""
    subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parents[1], check=True, capture_output=True)


@pytest.mark.parametrize('profile,scope', [
    (LEGACY_MAPPING, 'group'),
    (TEMPLATE_FRAMEWORK_MAPPING, 'dataset'),
    (PROJECT_MAPPING, 'project'),
])
def test_profiles_reuse_preparation_and_keep_context_state_independent(db, django_assert_num_queries, profile, scope):
    project = Project.objects.create(title='Selected project')
    other = Project.objects.create(title='Other project')
    snapshot = Snapshot.objects.create(project=project, title='Saved')
    path = 'project/dataset/title'
    add_answer(project, path, 'Saved title', snapshot=snapshot, set_index=1)
    add_answer(project, path, 'Current title', set_index=1)
    add_answer(other, path, 'Other title', set_index=1)
    selection = ExportDataset('1', 'Record', {'set_prefix': '', 'set_index': 1})

    with django_assert_num_queries(1):
        reader = profile.build_reader(project, snapshot=snapshot)
    with django_assert_num_queries(0):
        first = reader(selection)
        second = reader(selection)
        assert first.get_text(path) == second.get_text(path) == 'Saved title'
        assert first.scope == second.scope == scope
        assert first.project is (None if profile is TEMPLATE_FRAMEWORK_MAPPING else project)
        assert first.values is second.values
        assert first.placements is second.placements
        assert first.prepared is second.prepared
        assert all(value.snapshot_id == snapshot.pk for value in first.get_values(path))
        first.warn('title', path, 'Only the first context')
        first.provenance = []
        first.record_mapping('title', sources=first.get_values(path), value='Saved title')
        assert first.issues
        assert first.provenance
        assert second.issues == []
        assert second.provenance is None
        assert reader(selection).issues == []
