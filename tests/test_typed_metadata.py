"""Typed provider answers and the reviewed 27 October 2026 TF source paths."""
from copy import deepcopy
from dataclasses import replace
from functools import partial
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot, Value
from rdmo.questions.models import Catalog, CatalogSection, Section

from rdmo_radar.exports.renderers import RadarExportRenderer
from rdmo_radar.exports.validation import get_radar_validation_errors
from rdmo_radar.factories import build_export_service, build_xml_export_service
from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING, compute_metadata, write_metadata
from rdmo_radar.mappings.template_framework.fields import TF_FIELDS, read_contributors
from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.fields import Source, read_names
from rdmo_radar.metadata.normalization import normalize_answer
from rdmo_radar.metadata.provenance import json_leaves, xml_leaves
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.types import Affiliation, FundingReference, Identifier, Keyword, PersonOrOrganization
from rdmo_radar.metadata.xml import parse_xml, to_xml_payload

from .helpers import (
    add_answer,
    add_data_management_role,
    add_namespaced_attribute,
    complete_metadata,
    make_data_management_mapping,
    make_data_management_project,
)
from .test_imports import make_context
from .test_value_scopes import add_page, add_question, add_questionset

ROR = 'https://ror.org/0387prb75'
ORCID = '0000-0002-1825-0097'
GND = 'https://d-nb.info/gnd/4079154-3'


def ror_display(name='Institute', identifier=ROR):
    return f'{name} <a href="{identifier}"><img alt="ROR logo"> {identifier}</a>'


def orcid_display(name='Doe, Jane'):
    return f'{name} <a href="https://orcid.org/{ORCID}"><img alt="ORCID logo"></a>'


def gnd_display(label='Term', identifier=GND):
    return f'{label} [<a href="{identifier}">{identifier.rsplit("/", 1)[-1]}</a>]'


@pytest.mark.parametrize('text,external_id,scheme,label,identifier', [
    (' Plain name ', '', None, 'Plain name', None),
    ('A < B & C', '', None, 'A < B & C', None),
    (ror_display(), '0387prb75', None, 'Institute', Identifier(ROR, 'ROR')),
    (orcid_display(), ORCID, None, 'Doe, Jane', Identifier(ORCID, 'ORCID')),
    (gnd_display() + ' | synonym', '4079154-3', None, 'Term', Identifier(GND, 'GND')),
    ('Term', '4079154-3', 'GND', 'Term', Identifier(GND, 'GND')),
    ('Institute', ROR, None, 'Institute', Identifier(ROR, 'ROR')),
    ('Institute', '0387prb75', 'ROR', 'Institute', Identifier(ROR, 'ROR')),
    ('Institute', '0387prb75', None, 'Institute', None),
    ('Term', 'http://purl.obolibrary.org/obo/EX_1', None, 'Term', None),
    (ror_display(''), '0387prb75', None, '', Identifier(ROR, 'ROR')),
    (ror_display(), '018mejw64', None, 'Institute', None),
    ('Term', 'https://[', None, 'Term', None),
])
def test_provider_normalization(text, external_id, scheme, label, identifier):
    result = normalize_answer(text, external_id, scheme=scheme)
    assert result.label == label
    assert result.identifier == identifier


@pytest.fixture
def project(db):
    project = Project.objects.create(title='Typed metadata')
    add_answer(project, 'project/dataset/title', 'Dataset two', set_index=2)
    return project


def metadata(project, index=2, **kwargs):
    service = build_export_service(project, profile=TEMPLATE_FRAMEWORK_MAPPING, **kwargs)
    return service.mapping(service.reader(index))


def test_both_keyword_sources_preserve_gnd_identity_and_free_text(project):
    add_answer(project, 'project/research_question/keywords', 'Free text')
    add_answer(project, 'project/research_question/keywords', gnd_display(),
               external_id='4079154-3', collection_index=3)
    add_answer(project, 'project/research_question/keywords/gnd', 'Term', external_id='4079154-3')
    add_answer(project, 'project/research_question/keywords/gnd', 'Term', external_id='4069254-0', collection_index=7)
    add_answer(project, 'project/research_question/keywords/gnd', 'Created free text', collection_index=8)
    result = metadata(project)
    assert result.metadata.keywords == [
        'Free text', Keyword('Term', 'GND', 'https://d-nb.info/gnd/', GND, '4079154-3'),
        Keyword('Term', 'GND', 'https://d-nb.info/gnd/', 'https://d-nb.info/gnd/4069254-0', '4069254-0'),
        'Created free text',
    ]
    assert result.issues == ()


def test_unsupported_terminology_keeps_label_and_warns(project):
    add_answer(project, 'project/research_question/keywords', 'Some term', external_id='http://example.test/term/1')
    result = metadata(project)
    assert result.metadata.keywords == ['Some term']
    assert any('Unsupported' in issue.reason for issue in result.issues)


def test_owner_preference_nested_affiliation_and_dataset_isolation(project):
    for suffix, text in (('given_name', 'Jane'), ('family_name', 'Doe'), ('orcid', ORCID)):
        add_answer(project, f'project/dataset/owner/{suffix}', text, set_prefix='2', set_index=3)
    add_answer(project, 'project/dataset/owner/organization/name', 'Institute', set_prefix='2|3', set_index=7)
    add_answer(project, 'project/dataset/owner/organization/name/identifier/value', '0387prb75',
               set_prefix='2|3', set_index=7)
    add_answer(project, 'project/dataset/owner/organization/name/identifier/type', 'ROR',
               set_prefix='2|3', set_index=7)
    add_answer(project, 'project/dataset/owner/name', 'Unrelated owner', set_prefix='20', set_index=3)
    add_answer(project, 'project/dataset/creator/name', 'Legacy creator', set_prefix='2')
    add_answer(project, 'project/coordination/organization', 'Coordination institute')
    result = metadata(project)
    assert len(result.metadata.creators) == 1
    creator = result.metadata.creators[0]
    assert (creator.name, creator.given_name, creator.family_name) == ('Doe, Jane', 'Jane', 'Doe')
    assert creator.identifiers == [Identifier(ORCID, 'ORCID')]
    assert creator.affiliations == [Affiliation('Institute', ROR, 'ROR')]
    assert any('Both source families' in issue.reason for issue in result.issues)


def test_legacy_creator_fallback(project):
    add_answer(project, 'project/dataset/creator/name', 'Legacy creator', set_prefix='2')
    result = metadata(project).metadata
    assert [person.name for person in result.creators] == ['Legacy creator']


@pytest.mark.parametrize('kind', ['ror', 'orcid', 'structured', 'plain'])
def test_inferred_creator_type_records_evidence_and_only_final_identifier_mappings(project, kind):
    base = 'project/dataset/owner'
    if kind == 'structured':
        add_answer(project, f'{base}/given_name', 'Jane', set_prefix='2')
        add_answer(project, f'{base}/family_name', 'Doe', set_prefix='2')
    else:
        text, external_id = {
            'ror': (ror_display(), ROR), 'orcid': (orcid_display(), ORCID), 'plain': ('Plain name', ''),
        }[kind]
        add_answer(project, f'{base}/name', text, external_id=external_id, set_prefix='2')
    if kind in ('ror', 'orcid'):
        # The same identity in a dedicated field must contribute evidence once.
        add_answer(project, f'{base}/{kind}', ROR if kind == 'ror' else ORCID, set_prefix='2')
    plain = metadata(project).metadata
    traced = metadata(project, collect_mapping=True)
    assert traced.metadata == plain
    creator = traced.metadata.creators[0]
    assert creator.name_type == ('Organizational' if kind == 'ror' else 'Personal')
    row = next(a for a in traced.provenance if a.field == 'creators[0].name_type' and not a.unsuccessful)
    paths = {s.value.attribute.path for s in row.sources}
    if kind == 'plain':
        assert not paths
        assert row.reason == 'Established source category default'
    elif kind == 'structured':
        assert paths == {f'{base}/given_name', f'{base}/family_name'}
        assert row.reason == 'Person inferred from structured name'
    else:
        assert paths == {f'{base}/name', f'{base}/{kind}'}
        assert kind.upper() in row.reason
        for suffix in ('value', 'identifier_type'):
            rows = [a for a in traced.provenance
                    if a.field == f'creators[0].identifiers[0].{suffix}' and not a.unsuccessful]
            assert len(rows) == 1
            assert {s.value.attribute.path for s in rows[0].sources} == paths
        source = complete_metadata(creators=[creator])
        from rdmo_radar.exports.renderers import RadarExportRenderer
        assert get_radar_validation_errors(RadarExportRenderer().render(to_xml_payload(source))) == ()
        assert to_api_payload(source)['creators']['creator'][0]['nameType'] == creator.name_type


@pytest.mark.parametrize('correct_value', [None, ''])
def test_incorrect_rights_holder_path_never_supplies_export_or_provenance(project, correct_value):
    incorrect_path = 'project/dataset/sharing/rights_holder'
    add_answer(project, incorrect_path, 'Incorrect source', set_index=2)
    if correct_value is not None:
        add_answer(project, 'project/dataset/ipr/rightsholder', correct_value, set_index=2)

    result = metadata(project, collect_mapping=True)

    assert result.metadata.rights_holders == []
    assert 'rightsHolders' not in to_api_payload(result.metadata)
    assert 'rightsHolders' not in to_xml_payload(result.metadata)
    assert all(getattr(getattr(source.value, 'attribute', None), 'path', None) != incorrect_path
               for attempt in result.provenance for source in attempt.sources)


def test_publisher_and_rights_holder_provider_identity(project):
    add_answer(project, 'project/dataset/curation/responsible_person/name', orcid_display(),
               external_id=ORCID, set_index=2)
    add_answer(project, 'project/dataset/ipr/rightsholder', ror_display(), external_id='0387prb75', set_index=2)
    incorrect_path = 'project/dataset/sharing/rights_holder'
    add_answer(project, incorrect_path, 'Incorrect source', set_index=2)
    result = metadata(project, collect_mapping=True)
    assert result.metadata.publishers == [PersonOrOrganization('Doe, Jane', identifiers=[Identifier(ORCID, 'ORCID')])]
    assert result.metadata.rights_holders == [PersonOrOrganization('Institute', identifiers=[Identifier(ROR, 'ROR')])]
    assert all(getattr(getattr(source.value, 'attribute', None), 'path', None) != incorrect_path
               for attempt in result.provenance for source in attempt.sources)
    assert not any('Both source families' in issue.reason for issue in result.issues)


def test_responsibility_options_and_boolean_rights_are_not_names(project):
    option = Option.objects.create(uri_prefix='https://example.test', uri_path='responsibility/library',
                                   text_lang1='Library')
    add_answer(project, 'project/dataset/curation/responsible_person/name', '', option=option, set_index=2)
    add_answer(project, 'project/dataset/ipr/owner/name', 'Yes', set_index=2)
    result = metadata(project)
    assert result.metadata.publishers == result.metadata.rights_holders == []
    assert any('not an entity name' in issue.reason for issue in result.issues)


def test_funders_split_names_and_ids_without_crossing_grants(project):
    for index, label, raw_id, number in ((1, 'First', '0387prb75', 'A'), (7, 'Second', '018mejw64', 'B')):
        add_answer(project, 'project/funder/name', ror_display(label, f'https://ror.org/{raw_id}'),
                   external_id=raw_id, set_index=index)
        add_answer(project, 'project/funder/grant_nr', number, set_index=index)
    add_answer(project, 'project/funder/id', 'marker only', set_index=7)
    result = metadata(project)
    assert [(f.funder_name, f.funder_identifier.value, f.award_number) for f in result.metadata.funding_references] == [
        ('First', ROR, 'A'), ('Second', 'https://ror.org/018mejw64', 'B'),
    ]
    assert result.issues == ()


@pytest.mark.parametrize('scheme,expected', [('Other', Identifier('local-17', 'Other')), ('ROR', None)])
def test_explicit_funder_scheme_never_invents_an_identifier(project, scheme, expected):
    add_answer(project, 'project/funder/name', 'Funder', external_id='local-17')
    add_answer(project, 'project/funder/id/type', scheme)
    add_answer(project, 'project/funder/id', 'collection marker')
    result = metadata(project)
    assert result.metadata.funding_references[0].funder_identifier == expected
    assert result.metadata.funding_references[0].funder_name == 'Funder'


def test_new_contributor_structure_types_identifiers_and_roles(project):
    entity = Option.objects.create(uri_prefix='https://rdmorganiser.github.io/terms', uri_path='partner-types/entity',
                                   text_lang1='Entität')
    add_answer(project, 'project/contributor/person_or_entity', '', option=entity, set_index=3)
    add_answer(project, 'project/contributor/name', ror_display(), external_id='0387prb75', set_index=3)
    add_answer(project, 'project/contributor/role', 'DataCurator', set_index=3)
    add_answer(project, 'project/contributor/given_name', 'Jane', set_index=8)
    add_answer(project, 'project/contributor/family_name', 'Doe', set_index=8)
    add_answer(project, 'project/contributor/orcid', ORCID, set_index=8)
    add_answer(project, 'project/contributor/organization', 'Institute', set_prefix='8')
    add_answer(project, 'project/contributor/organization/ror', '0387prb75', set_prefix='8')
    add_answer(project, 'project/contributor/role', 'Unknown role', set_index=8)
    add_answer(project, 'project/partner/name', 'Legacy contributor')
    result = metadata(project)
    first, second = result.metadata.contributors
    assert (first.name, first.name_type, first.contributor_type) == ('Institute', 'Organizational', 'DataCurator')
    assert first.identifiers == [Identifier(ROR, 'ROR')]
    assert (second.name, second.contributor_type) == ('Doe, Jane', 'Other')
    assert second.affiliations == [Affiliation('Institute', ROR, 'ROR')]
    assert any('Unknown or conflicting contributor roles' in issue.reason for issue in result.issues)


def test_smp_autocomplete_name_and_affiliation(project):
    add_answer(project, 'project/contributor/orcid-autocomplete', orcid_display(), external_id=ORCID, set_index=3)
    add_answer(project, 'project/contributor/organization/ror-autocomplete', ror_display(),
               external_id='0387prb75', set_index=3)
    person = metadata(project).metadata.contributors[0]
    assert person.name == 'Doe, Jane'
    assert person.identifiers == [Identifier(ORCID, 'ORCID')]
    assert person.affiliations == [Affiliation('Institute', ROR, 'ROR')]


def test_identifier_only_new_family_does_not_hide_legacy_names(project):
    add_answer(project, 'project/dataset/owner/orcid', ORCID, set_prefix='2')
    add_answer(project, 'project/dataset/creator/name', 'Legacy', set_prefix='2')
    add_answer(project, 'project/contributor/role', 'DataCurator')
    add_answer(project, 'project/partner/name', 'Legacy contributor')
    result = metadata(project)
    assert [person.name for person in result.metadata.creators] == ['Legacy']
    assert [person.name for person in result.metadata.contributors] == ['Legacy contributor']
    assert sum('Identifier/type-only' in issue.reason for issue in result.issues) == 2


@pytest.mark.parametrize('text,external_id,explicit_id', [
    (orcid_display(), ORCID, '0000-0001-2345-6789'),
    (ror_display(), '018mejw64', ROR),
    (orcid_display(), ORCID, ROR),
])
def test_disputed_identity_is_not_restored_from_another_field(project, text, external_id, explicit_id):
    add_answer(project, 'project/dataset/owner/name', text, external_id=external_id, set_prefix='2')
    add_answer(project, 'project/dataset/owner/orcid', explicit_id, set_prefix='2')
    result = metadata(project)
    assert result.metadata.creators[0].identifiers == []
    assert any('Conflicting entity identifiers' in issue.reason for issue in result.issues)


def test_entity_discriminator_and_identifier_conflict(project):
    entity = Option.objects.create(uri_prefix='https://rdmorganiser.github.io/terms', uri_path='partner-types/entity',
                                   text_lang1='Entity')
    add_answer(project, 'project/contributor/name', orcid_display(), external_id=ORCID)
    add_answer(project, 'project/contributor/person_or_entity', '', option=entity)
    result = metadata(project)
    assert result.metadata.contributors[0].name_type == 'Organizational'
    assert result.metadata.contributors[0].identifiers == []
    assert any('Entity type conflicts' in issue.reason for issue in result.issues)


@pytest.mark.parametrize('role_path', ['project/contributor/role', 'dmp/contributor/role'])
def test_role_in_scalar_child_questionset_belongs_to_its_contributor(project, role_path):
    attach_catalog(project)
    page = add_page(project, 'project/contributor/name', collection=True)
    scalar_child = add_questionset(page)
    add_question(scalar_child, role_path)
    add_answer(project, 'project/contributor/name', 'Contributor', set_index=3)
    add_answer(project, role_path, 'DataCurator', set_prefix='3')
    assert metadata(project).metadata.contributors[0].contributor_type == 'DataCurator'


@pytest.mark.parametrize('role,expected', [('DataCurator', 'DataCurator'), ('Unknown', 'Other')])
def test_role_alias_requires_shared_catalog_group(project, role, expected):
    attach_catalog(project)
    page = add_page(project, 'project/contributor/name', collection=True)
    add_question(page, 'dmp/contributor/role')
    add_answer(project, 'project/contributor/name', 'Contributor')
    add_answer(project, 'dmp/contributor/role', role)
    assert metadata(project).metadata.contributors[0].contributor_type == expected


def test_unrelated_role_alias_is_not_joined_by_index(project):
    attach_catalog(project)
    add_page(project, 'project/contributor/name', collection=True)
    page = add_page(project, 'unrelated/collection', collection=True)
    add_question(page, 'dmp/contributor/role')
    add_answer(project, 'project/contributor/name', 'Contributor')
    add_answer(project, 'dmp/contributor/role', 'DataCurator')
    result = metadata(project)
    assert result.metadata.contributors[0].contributor_type == 'Other'
    assert any('no shared catalog group' in issue.reason for issue in result.issues)


def attach_catalog(project):
    catalog = Catalog.objects.create(uri_prefix='https://example.test', uri_path='typed')
    section = Section.objects.create(uri_prefix='https://example.test', uri_path='typed-section')
    CatalogSection.objects.create(catalog=catalog, section=section)
    project.catalog = catalog
    project.save()


def test_catalog_owner_affiliation_with_intervening_noncollection_level(project):
    attach_catalog(project)
    page = add_page(project, 'project/dataset/id', collection=True)
    owners = add_questionset(page, 'project/dataset/owner/name', collection=True)
    add_question(owners, 'project/dataset/owner/orcid')
    organisations = add_questionset(owners, 'project/dataset/owner/organization/name', collection=True)
    identifiers = add_questionset(organisations)
    add_question(identifiers, 'project/dataset/owner/organization/name/identifier/value')
    add_question(identifiers, 'project/dataset/owner/organization/name/identifier/type')
    add_answer(project, 'project/dataset/id', 'Dataset two', set_index=2)
    add_answer(project, 'project/dataset/owner/name', 'Jane', set_prefix='2', set_index=3)
    add_answer(project, 'project/dataset/owner/orcid', ORCID, set_prefix='2', set_index=3)
    add_answer(project, 'project/dataset/owner/organization/name', 'Institute', set_prefix='2|3', set_index=7)
    add_answer(project, 'project/dataset/owner/organization/name/identifier/value', ROR, set_prefix='2|3|7')
    add_answer(project, 'project/dataset/owner/organization/name/identifier/type', 'ROR', set_prefix='2|3|7')
    add_answer(project, 'project/dataset/owner/name', 'Other dataset owner', set_prefix='20', set_index=3)
    person = metadata(project).metadata.creators[0]
    assert person.name == 'Jane'
    assert person.affiliations == [Affiliation('Institute', ROR, 'ROR')]


def test_nested_owner_identifier_does_not_create_an_orphan_person(project):
    attach_catalog(project)
    page = add_page(project, 'project/dataset/id', collection=True)
    owners = add_questionset(page, 'project/dataset/owner/name', collection=True)
    identifiers = add_questionset(owners)
    add_question(identifiers, 'project/dataset/owner/orcid')
    add_answer(project, 'project/dataset/id', 'Dataset two', set_index=2)
    add_answer(project, 'project/dataset/owner/name', 'Jane', set_prefix='2', set_index=3)
    add_answer(project, 'project/dataset/owner/orcid', ORCID, set_prefix='2|3')
    result = metadata(project)
    assert len(result.metadata.creators) == 1
    assert result.metadata.creators[0].identifiers == [Identifier(ORCID, 'ORCID')]
    assert result.issues == ()


def test_ambiguous_preferred_attribute_does_not_enable_legacy_fallback(project):
    path = 'project/dataset/owner/name'
    for namespace in ('https://a.test', 'https://b.test'):
        attribute = add_namespaced_attribute(path, namespace)
        project.values.create(attribute=attribute, text='Owner', set_prefix='2')
    add_answer(project, 'project/dataset/creator/name', 'Legacy', set_prefix='2')
    result = metadata(project)
    assert result.metadata.creators == []
    assert any('Ambiguous Attribute' in issue.reason for issue in result.issues)


def test_publisher_callable_can_be_replaced_independently(project):
    fields = replace(TF_FIELDS, readers={**TF_FIELDS.readers,
        'publishers': lambda context, *, target: [PersonOrOrganization('Custom publisher')]})
    assert metadata(project, mapping=partial(compute_metadata, fields=fields)).metadata.publishers[0].name == (
        'Custom publisher'
    )
    add_answer(project, 'local/publisher', 'Chosen publisher', set_index=2)
    fields = replace(fields, readers={**fields.readers,
        'publishers': partial(read_names, source=Source('local/publisher'))})
    mapping = partial(compute_metadata, fields=fields)
    assert metadata(project, mapping=mapping).metadata.publishers[0].name == 'Chosen publisher'


def test_typed_keyword_import_keeps_labels_and_reports_identity_loss(db):
    context = make_context()
    write_metadata(context.import_plugin, complete_metadata(keywords=[Keyword('Term', 'GND', value_uri=GND)]),
                   context.coordinates.set_index, context=context)
    assert any(value.text == 'Term' for value in context.import_plugin.values)
    assert any(issue.field == 'keywords' and 'labels' in issue.reason for issue in context.issues)


def test_typed_xml_validation_roundtrip_and_independent_rest_expectations():
    from rdmo_radar.exports.renderers import RadarExportRenderer

    source = complete_metadata(
        creators=[PersonOrOrganization('Creator', identifiers=[Identifier(ORCID, 'ORCID')],
                                      affiliations=[Affiliation('Institute', ROR, 'ROR')])],
        keywords=['Free text', Keyword('Term', 'GND', 'https://d-nb.info/gnd/', GND, '4079154-3')],
        publishers=[PersonOrOrganization('Institute', identifiers=[Identifier(ROR, 'ROR')])],
        funding_references=[FundingReference('Funder', Identifier(ROR, 'ROR'), 'GRANT')],
    )
    original = deepcopy(source)
    xml = RadarExportRenderer().render(to_xml_payload(source))
    assert get_radar_validation_errors(xml) == ()
    parsed = parse_xml(ElementTree.fromstring(xml))
    assert parsed.keywords == source.keywords
    assert parsed.creators[0].affiliations[0] == Affiliation('Institute', ROR, 'ROR', 'https://ror.org/')
    assert parsed.funding_references[0].funder_identifier.scheme_uri == 'https://ror.org/'
    payload = to_api_payload(source)
    assert payload['keywords'] == {'keyword': [
        {'value': 'Free text'}, {'value': 'Term', 'keywordScheme': 'GND', 'schemeURI': 'https://d-nb.info/gnd/',
                                 'valueURI': GND, 'classificationCode': '4079154-3'},
    ]}
    assert payload['publishers'] == {'publisher': [
        {'value': 'Institute', 'nameIdentifier': ROR, 'nameIdentifierScheme': 'ROR', 'schemeURI': 'https://ror.org/'},
    ]}
    assert source == original


def test_explicit_scheme_uris_and_free_text_affiliation_scheme_are_preserved():
    from rdmo_radar.exports.renderers import RadarExportRenderer

    custom_uri = 'https://example.test/registries/organisation/'
    source = complete_metadata(
        keywords=[Keyword('Term', 'GND', value_uri=GND)],
        creators=[PersonOrOrganization('Creator', affiliations=[
            Affiliation('Institute', 'local-1', 'Local Registry', custom_uri),
        ])],
        publishers=[PersonOrOrganization('Publisher', identifiers=[
            Identifier('local-2', 'Other', scheme_uri=custom_uri),
        ])],
    )
    payload = to_api_payload(source)
    assert payload['keywords']['keyword'][0]['schemeURI'] == 'https://d-nb.info/gnd/'
    assert payload['creators']['creator'][0]['creatorAffiliation'] == {
        'value': 'Institute', 'affiliationIdentifier': 'local-1',
        'affiliationIdentifierScheme': 'Local Registry', 'schemeURI': custom_uri,
    }
    assert payload['publishers']['publisher'][0]['schemeURI'] == custom_uri
    xml = RadarExportRenderer().render(to_xml_payload(source))
    assert get_radar_validation_errors(xml) == ()
    parsed = parse_xml(ElementTree.fromstring(xml))
    assert parsed.creators[0].affiliations[0] == source.creators[0].affiliations[0]
    assert parsed.publishers[0].identifiers[0].scheme_uri == custom_uri


@pytest.mark.parametrize('kind', ['api', 'xml'])
def test_offline_preparation_provenance_snapshot_and_query_contract(
    project, kind, monkeypatch, django_assert_num_queries,
):
    import requests

    add_answer(project, 'project/dataset/owner/name', orcid_display(), external_id=ORCID, set_prefix='2')
    add_answer(project, 'project/research_question/keywords/gnd', gnd_display(), external_id='4079154-3')
    add_answer(project, 'project/funder/name', ror_display(), external_id='0387prb75')
    snapshot = Snapshot.objects.create(project=project, title='Saved')
    factory = build_export_service if kind == 'api' else build_xml_export_service
    service = factory(project, profile=TEMPLATE_FRAMEWORK_MAPPING, snapshot=snapshot, collect_mapping=True)
    project.values.filter(snapshot=None, attribute__path='project/dataset/owner/name').update(text='Changed live')
    before = project.values.count()
    monkeypatch.setattr(requests.sessions.Session, 'request',
                        Mock(side_effect=AssertionError('Network during preparation')))
    with django_assert_num_queries(0):
        result = service.compute_payload(2, 'owner@example.test') if kind == 'api' else service.compute_files([2])[0]
        again = service.compute_payload(2, 'owner@example.test') if kind == 'api' else service.compute_files([2])[0]
    leaves = dict(json_leaves(result.payload)) if kind == 'api' else xml_leaves(result.xml_data)
    assert not any(row.outcome == 'untraced' for row in result.provenance)
    assert any(row.field == 'keywords[0].value_uri' and row.output_path for row in result.provenance)
    for row in result.provenance:
        if row.output_path:
            assert leaves[row.output_path] == row.output_value
        for source in row.sources:
            if hasattr(source.value, 'snapshot_id'):
                assert source.value.snapshot_id == snapshot.pk
    assert result.issues == again.issues
    assert project.values.count() == before


@pytest.fixture
def staff_project(db):
    return make_data_management_project()


def test_all_roles_expand_with_stable_indices_and_export_in_both_formats(staff_project, django_assert_num_queries):
    for i in range(9):
        add_data_management_role(staff_project, i)
    service = build_export_service(staff_project, profile=make_data_management_mapping(), collect_mapping=True)
    expected = [
        'ProjectLeader',
        'ProjectManager',
        'WorkPackageLeader',
        'DataManager',
        'DataCurator',
        'DataCollector',
        'Editor',
        'Other',
    ]
    for index in (1, 10):
        with django_assert_num_queries(0):
            result = service.compute_payload(index, 'user@example.test')
        people = result.payload['descriptiveMetadata']['contributors']['contributor']
        assert [p['contributorType'] for p in people] == [
            'PROJECT_LEADER',
            'PROJECT_MANAGER',
            'WORK_PACKAGE_LEADER',
            'DATA_MANAGER',
            'DATA_CURATOR',
            'DATA_COLLECTOR',
            'EDITOR',
            'OTHER',
        ]
        # Inspect canonical values as well as projected evidence for each output entry.
        canonical = service.mapping(service.reader(index)).metadata.contributors
        assert [p.contributor_type for p in canonical] == expected
        for i, role in enumerate(expected):
            name = next(a for a in result.provenance if a.field == f'contributors[{i}].name' and a.output_path)
            assert name.output_value == 'Jane Doe'
            assert name.sources[0].value.set_index == 3
            role_row = next(
                a for a in result.provenance if a.field == f'contributors[{i}].contributor_type' and a.output_path
            )
            assert role_row.sources
            assert role_row.value == role
        xml = RadarExportRenderer().render(to_xml_payload(complete_metadata(contributors=canonical)))
        assert get_radar_validation_errors(xml) == ()
        assert any('Data steward' in issue.reason for issue in result.issues)


def test_missing_and_unknown_roles_keep_people_as_other(staff_project):
    service = build_export_service(staff_project, profile=make_data_management_mapping(), collect_mapping=True)
    result = service.mapping(service.reader(1))
    assert result.metadata.contributors[0].contributor_type == 'Other'
    assert any('No contributor role' in issue.reason for issue in result.issues)
    add_data_management_role(staff_project, 1)
    unknown = Option.objects.create(uri_prefix='https://unrelated.test', uri_path='dr01', text_lang1='Project manager')
    add_answer(
        staff_project,
        'project/data_management/role',
        '',
        option=unknown,
        set_prefix='0',
        set_index=3,
        collection_index=22,
    )
    service = build_export_service(staff_project, profile=make_data_management_mapping(), collect_mapping=True)
    result = service.mapping(service.reader(1))
    assert [p.contributor_type for p in result.metadata.contributors] == ['ProjectManager', 'Other']
    assert any(a.outcome == 'rejected' for a in result.provenance)


def test_deduplication_retains_existing_details_and_rebases_following_entries(staff_project):
    for suffix, text in [('name', 'Preferred name'), ('orcid', ORCID), ('role', 'DataCurator')]:
        add_answer(staff_project, f'project/contributor/{suffix}', text, set_index=7)
    add_data_management_role(staff_project, 5)
    add_answer(staff_project, 'project/data_management/name', 'Second person', set_prefix='0', set_index=4)
    add_data_management_role(staff_project, 7, person=4)
    service = build_export_service(staff_project, profile=make_data_management_mapping(), collect_mapping=True)
    result = service.compute_payload(1, 'user@example.test')
    people = result.payload['descriptiveMetadata']['contributors']['contributor']
    assert [p['contributorName'] for p in people] == ['Preferred name', 'Second person']
    assert any('differing details' in issue.reason for issue in result.issues)
    assert any(a.outcome == 'skipped' and 'Duplicate contributor' in a.reason for a in result.provenance)
    second = next(a for a in result.provenance if a.field == 'contributors[1].name' and a.output_path)
    assert second.output_value == 'Second person'
    assert second.sources[0].value.set_index == 4


def test_identifier_only_person_is_not_exported_and_snapshots_remain_isolated(staff_project):
    add_data_management_role(staff_project, 1)
    snapshot = Snapshot.objects.create(project=staff_project, title='Saved')
    staff_project.values.filter(snapshot=None, attribute__path='project/data_management/name').delete()
    current = build_export_service(staff_project, profile=make_data_management_mapping())
    saved = build_export_service(staff_project, profile=make_data_management_mapping(), snapshot=snapshot)
    assert current.mapping(current.reader(1)).metadata.contributors == []
    assert saved.mapping(saved.reader(1)).metadata.contributors[0].name == 'Jane Doe'


def test_conflicting_orcid_does_not_restore_identity_or_cross_person_groups(staff_project):
    add_data_management_role(staff_project, 1)
    add_answer(
        staff_project,
        'project/data_management/orcid',
        '0000-0003-4553-3671',
        set_prefix='0',
        set_index=3,
        collection_index=1,
    )
    service = build_export_service(staff_project, profile=make_data_management_mapping(), collect_mapping=True)
    result = service.mapping(service.reader(1))
    assert result.metadata.contributors[0].identifiers == []
    assert result.metadata.contributors[0].contributor_type == 'ProjectManager'
    assert result.issues


def test_same_names_without_identifiers_do_not_merge_different_roles(staff_project):
    staff_project.values.filter(attribute__path='project/data_management/orcid').delete()
    add_data_management_role(staff_project, 5)
    add_answer(staff_project, 'project/contributor/name', 'Jane Doe')
    add_answer(staff_project, 'project/contributor/role', 'ProjectManager')
    service = build_export_service(staff_project, profile=make_data_management_mapping())
    people = service.mapping(service.reader(1)).metadata.contributors
    assert [p.contributor_type for p in people] == ['ProjectManager', 'DataCurator']


def test_catalog_group_ancestry_keeps_people_roles_and_orcids_together(staff_project):
    staff_project.values.filter(attribute__path__startswith='project/data_management/').delete()
    attach_catalog(staff_project)
    page = add_page(staff_project)
    people = add_questionset(page, 'project/data_management/name', collection=True)
    details = add_questionset(people)
    add_question(details, 'project/data_management/orcid')
    add_question(details, 'project/data_management/role')
    for index in (3, 7):
        add_answer(staff_project, 'project/data_management/name', f'Person {index}', set_prefix='0', set_index=index)
        add_answer(
            staff_project,
            'project/data_management/orcid',
            ORCID if index == 3 else '0000-0003-4553-3671',
            set_prefix=f'0|{index}',
        )
        add_data_management_role(staff_project, 1 if index == 3 else 5, prefix=f'0|{index}', person=0)
    service = build_export_service(staff_project, profile=make_data_management_mapping())
    people = service.mapping(service.reader(1)).metadata.contributors
    assert [(p.name, p.contributor_type, p.identifiers[0].value) for p in people] == [
        ('Person 3', 'ProjectManager', ORCID),
        ('Person 7', 'DataCurator', '0000-0003-4553-3671'),
    ]


@pytest.mark.parametrize('trace', [False, True])
def test_disabled_contributors_do_not_resolve_ambiguous_unused_attributes(trace):
    path = 'project/data_management/name'
    values = {}
    for namespace in ('one', 'two'):
        attribute = Attribute(uri=f'https://{namespace}.test/domain/{path}', path=path)
        values[attribute.uri] = [Value(attribute=attribute, text='Person')]
    context = ProjectReadContext(values, {}, provenance=[] if trace else None)
    assert read_contributors(context, target='contributors') == []
    assert not context.issues
    if trace:
        notes = [a for a in context.provenance if 'mapping is disabled' in a.reason]
        assert {s.value.attribute.uri for a in notes for s in a.sources} == set(values)
        assert all(a.outcome == 'skipped' for a in notes)
