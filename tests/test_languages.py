"""Language names and codes map to the controlled RADAR vocabulary offline."""
from dataclasses import replace
from functools import partial
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot

from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import get_radar_validation_errors
from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.imports import RadarTemplateFrameworkImport as RadarImport
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING, compute_metadata, write_metadata
from rdmo_radar.mappings.template_framework.fields import TF_FIELDS
from rdmo_radar.mappings.template_framework.vocabulary import LANGUAGE_OPTIONS
from rdmo_radar.metadata.fields import Source, read_language
from rdmo_radar.metadata.languages import normalize_language
from rdmo_radar.metadata.types import RadarMetadata
from rdmo_radar.metadata.xml import to_xml_payload

from .helpers import add_answer, add_attribute, add_namespaced_attribute, complete_metadata

LANGUAGE_PATH = 'project/dataset/language'
EXAMPLES = [
    ('English', 'Englisch', 'en', 'eng'),
    ('German', 'Deutsch', 'de', 'deu'),
    ('French', 'Französisch', 'fr', 'fra'),
    ('Danish', 'Dänisch', 'da', 'dan'),
    ('Dutch', 'Niederländisch', 'nl', 'nld'),
    ('Swedish', 'Schwedisch', 'sv', 'swe'),
    ('Finnish', 'Finnisch', 'fi', 'fin'),
    ('Italian', 'Italienisch', 'it', 'ita'),
    ('Spanish', 'Spanisch', 'es', 'spa'),
    ('Portuguese', 'Portugiesisch', 'pt', 'por'),
    ('Polish', 'Polnisch', 'pl', 'pol'),
    ('Czech', 'Tschechisch', 'cs', 'ces'),
]


@pytest.mark.parametrize('english,german,short,code', EXAMPLES)
def test_supported_names_and_codes(english, german, short, code):
    for value in (english, german, short, code, f'  {german.upper()}  '):
        assert normalize_language(value) == code


@pytest.mark.parametrize('answer,code', [
    ('ger', 'deu'), ('fre', 'fra'), ('dut', 'nld'), ('cze', 'ces'),
    ('Daenisch', 'dan'), ('FRANZO\u0308SISCH', 'fra'), ('Nederlands', 'nld'), ('Español', 'spa'),
])
def test_input_aliases_use_canonical_schema_codes(answer, code):
    assert normalize_language(answer) == code


@pytest.mark.parametrize('answer', ['', 'Deutsch, Englisch', 'de-DE', 'Unknown language', 'jpn'])
def test_unknown_or_ambiguous_text_has_no_implicit_default(answer):
    assert normalize_language(answer) is None


@pytest.fixture
def project(db):
    project = Project.objects.create(title='Language mapping')
    add_answer(project, 'project/dataset/title', 'Dataset', set_index=1)
    return project


def test_all_language_names_reach_both_exports_and_validate(project):
    for index, (_, german, _, _) in enumerate(EXAMPLES, 1):
        if index != 1:
            add_answer(project, 'project/dataset/title', f'Dataset {index}', set_index=index)
        add_answer(project, LANGUAGE_PATH, german, set_index=index)
    service = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING, collect_mapping=True)
    xml_service = build_xml_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING)
    for index, (_, _, _, code) in enumerate(EXAMPLES, 1):
        result = service.compute_payload(index, 'owner@example.test')
        assert result.payload['descriptiveMetadata']['language'] == code.upper()
        language = next(row for row in result.provenance if row.field == 'language' and row.output_path)
        assert language.value == code
        assert language.output_value == code.upper()
        assert language.sources[0].value.set_index == index
        xml = xml_service.compute_files([index])[0].xml_data
        root = ElementTree.fromstring(xml)
        assert root.findtext('{http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements}language') == code
        complete_xml = RadarExportRenderer().render(to_xml_payload(complete_metadata(language=code)))
        assert get_radar_validation_errors(complete_xml) == ()


@pytest.mark.parametrize('short,code', [('en', 'eng'), ('de', 'deu'), ('fr', 'fra'), ('da', 'dan')])
def test_existing_and_additional_options_use_identity_not_display_text(project, short, code):
    option = Option.objects.create(uri_prefix='https://example.test', uri_path=f'language/{short}',
                                   text_lang1='Display label does not control mapping')
    add_answer(project, LANGUAGE_PATH, '', option=option, set_index=1)
    service = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING)
    result = service.compute_payload(1, 'owner@example.test')
    assert result.payload['descriptiveMetadata']['language'] == code.upper()
    assert result.issues == ()


def test_equivalent_text_and_options_are_one_language_with_all_sources(project):
    option = Option.objects.create(uri_prefix='https://example.test', uri_path='language/de', text_lang1='Deutsch')
    for index, text in enumerate(('Deutsch', 'de', 'GER', 'deu')):
        add_answer(project, LANGUAGE_PATH, text, set_index=1, collection_index=index)
    add_answer(project, LANGUAGE_PATH, '', option=option, set_index=1, collection_index=4)
    service = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING, collect_mapping=True)
    result = service.compute_payload(1, 'owner@example.test')
    assert result.payload['descriptiveMetadata']['language'] == 'DEU'
    assert result.issues == ()
    language = next(row for row in result.provenance if row.field == 'language' and row.output_path)
    assert len(language.sources) == 5


@pytest.mark.parametrize('answers', [
    ['Deutsch', 'Englisch'], ['Deutsch', 'Unknown'], ['jpn'], ['Deutsch, Englisch'],
])
def test_conflicting_and_unsupported_answers_are_omitted_with_diagnostics(project, answers):
    for index, text in enumerate(answers):
        add_answer(project, LANGUAGE_PATH, text, set_index=1, collection_index=index)
    service = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING, collect_mapping=True)
    result = service.compute_payload(1, 'owner@example.test')
    assert 'language' not in result.payload['descriptiveMetadata']
    assert any(issue.field == 'language' and issue.source == LANGUAGE_PATH for issue in result.issues)
    assert any(row.field == 'language' and row.outcome == 'rejected' for row in result.provenance)
    xml = build_xml_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING).compute_files([1])[0].xml_data
    assert ElementTree.fromstring(xml).find(
        '{http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements}language',
    ) is None


def test_unknown_option_cannot_match_a_translated_language_label(project):
    option = Option.objects.create(uri_prefix='https://example.test', uri_path='unknown', text_lang1='Deutsch')
    add_answer(project, LANGUAGE_PATH, '', option=option, set_index=1)
    result = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING).compute_payload(1, 'owner@example.test')
    assert 'language' not in result.payload['descriptiveMetadata']
    assert any(issue.field == 'language' for issue in result.issues)


def test_option_namespace_ambiguity_is_preserved(project):
    for index, prefix in enumerate(('https://a.test', 'https://b.test')):
        option = Option.objects.create(uri_prefix=prefix, uri_path='language/de', text_lang1='Deutsch')
        add_answer(project, LANGUAGE_PATH, '', option=option, set_index=1, collection_index=index)
    result = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING).compute_payload(1, 'owner@example.test')
    assert 'language' not in result.payload['descriptiveMetadata']
    assert any(issue.reason == 'Ambiguous Option path' for issue in result.issues)


@pytest.mark.parametrize('answer', [None, '', '  '])
def test_absent_or_blank_language_is_omitted_without_warning(project, answer):
    if answer is not None:
        add_answer(project, LANGUAGE_PATH, answer, set_index=1)
    result = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING).compute_payload(1, 'owner@example.test')
    assert 'language' not in result.payload['descriptiveMetadata']
    assert result.issues == ()


def test_snapshot_and_dataset_scope_stay_offline(project, monkeypatch, django_assert_num_queries):
    import requests

    add_answer(project, LANGUAGE_PATH, 'Deutsch', set_index=1)
    add_answer(project, 'project/dataset/title', 'Tenth', set_index=10)
    add_answer(project, LANGUAGE_PATH, 'Englisch', set_index=10)
    snapshot = Snapshot.objects.create(project=project, title='Saved')
    project.values.filter(snapshot=None, attribute__path=LANGUAGE_PATH, set_index=1).update(text='Dänisch')
    live = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING)
    saved = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING, snapshot=snapshot, collect_mapping=True)
    monkeypatch.setattr(requests.sessions.Session, 'request',
                        Mock(side_effect=AssertionError('Language lookup request')))
    with django_assert_num_queries(0):
        assert live.compute_payload(1, 'owner@example.test').payload['descriptiveMetadata']['language'] == 'DAN'
        result = saved.compute_payload(1, 'owner@example.test')
        assert result.payload['descriptiveMetadata']['language'] == 'DEU'
        assert saved.compute_payload(10, 'owner@example.test').payload['descriptiveMetadata']['language'] == 'ENG'
    language = next(row for row in result.provenance if row.field == 'language' and row.output_path)
    assert all(source.value.snapshot_id == snapshot.pk for source in language.sources)


def test_extended_option_vocabulary_remains_importable_when_installed(db):
    attribute = add_attribute(LANGUAGE_PATH)
    option = Option.objects.create(uri_prefix='https://rdmorganiser.github.io/terms', uri_path='language/fr',
                                   text_lang1='Français')
    plugin = RadarImport('radar', 'RADAR', 'rdmo_radar.imports.RadarTemplateFrameworkImport')
    assert write_metadata(plugin, RadarMetadata(language='fra'), 3, existing_values={}) == ()
    assert [(value.attribute_id, value.option_id, value.set_index) for value in plugin.values] == [
        (attribute.pk, option.pk, 3),
    ]


@pytest.mark.parametrize('kind', ['api', 'xml'])
@pytest.mark.parametrize('answer,code', [('Dänisch', 'dan'), ('Unsupported', None), (None, None)])
def test_mapping_explicitly_selects_language_attribute_without_tf_fallback(project, kind, answer, code):
    add_answer(project, LANGUAGE_PATH, 'Deutsch', set_index=1)
    custom_uri = 'https://custom.test/domain/research/language'
    if answer is not None:
        attribute = add_namespaced_attribute('research/language', 'https://custom.test')
        project.values.create(attribute=attribute, text=answer, set_index=1)
    mapping = replace(
        TEMPLATE_FRAMEWORK_MAPPING,
        compute_metadata=partial(compute_metadata, fields=replace(TF_FIELDS, readers={**TF_FIELDS.readers,
            'language': partial(read_language, source=Source(custom_uri), option_map=LANGUAGE_OPTIONS)})),
    )
    factory = build_export_service if kind == 'api' else build_xml_export_service
    service = factory(project, profile=mapping, collect_mapping=True)

    if kind == 'api':
        result = service.compute_payload(1, 'owner@example.test')
        assert result.payload['descriptiveMetadata'].get('language') == (code.upper() if code else None)
    else:
        result = service.compute_files([1])[0]
        root = ElementTree.fromstring(result.xml_data)
        assert root.findtext('{http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements}language') == code
    attempts = [row for row in result.provenance if row.field == 'language']
    assert attempts
    assert all(source.reference == custom_uri for row in attempts for source in row.sources)
    if answer == 'Unsupported':
        assert any(issue.field == 'language' and issue.source == custom_uri for issue in result.issues)
