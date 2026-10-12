"""Catalog-aware behavior contracts, independent of the answer access implementation."""
import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from rdmo.domain.models import Attribute
from rdmo.projects.models import Project, Value
from rdmo.questions.models import (
    Catalog,
    CatalogSection,
    Page,
    PageQuestion,
    PageQuestionSet,
    Question,
    QuestionSet,
    QuestionSetQuestion,
    QuestionSetQuestionSet,
    Section,
    SectionPage,
)
from rdmo.views.utils import ProjectWrapper

from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.rdmo import RDMOReadContext

from .helpers import add_answer, add_attribute, export_for, read_metadata


@pytest.fixture
def scope_project(db):
    catalog = Catalog.objects.create(uri_prefix='https://example.test', uri_path='scope-catalog')
    section = Section.objects.create(uri_prefix='https://example.test', uri_path='scope-section')
    CatalogSection.objects.create(catalog=catalog, section=section, order=0)
    return Project.objects.create(title='Scope project', catalog=catalog)


def add_page(project, path=None, collection=False):
    page = Page.objects.create(
        uri_prefix='https://example.test', uri_path=f'page-{Page.objects.count()}',
        attribute=add_attribute(path) if path else None, is_collection=collection,
    )
    SectionPage.objects.create(section=project.catalog.sections.first(), page=page, order=Page.objects.count())
    return page


def add_questionset(parent, path=None, collection=False):
    questionset = QuestionSet.objects.create(
        uri_prefix='https://example.test', uri_path=f'set-{QuestionSet.objects.count()}',
        attribute=add_attribute(path) if path else None, is_collection=collection,
    )
    attach_questionset(parent, questionset)
    return questionset


def attach_questionset(parent, questionset):
    if isinstance(parent, Page):
        PageQuestionSet.objects.create(page=parent, questionset=questionset, order=0)
    else:
        QuestionSetQuestionSet.objects.create(parent=parent, questionset=questionset, order=0)


def add_question(parent, path):
    question = Question.objects.create(
        uri_prefix='https://example.test', uri_path=f'question-{Question.objects.count()}',
        attribute=add_attribute(path), widget_type='text', value_type='text',
    )
    if isinstance(parent, Page):
        PageQuestion.objects.create(page=parent, question=question, order=0)
    else:
        QuestionSetQuestion.objects.create(questionset=parent, question=question, order=0)
    return question


@pytest.mark.parametrize('marker_kind', ['page', 'questionset'])
def test_empty_dataset_collection_is_discovered_without_questions(scope_project, marker_kind):
    if marker_kind == 'page':
        add_page(scope_project, 'project/dataset/id', collection=True)
        prefix = ''
    else:
        page = add_page(scope_project)
        middle = add_questionset(page)
        add_questionset(middle, 'project/dataset/id', collection=True)
        prefix = '0|0'
    add_answer(scope_project, 'project/dataset/id', 'Marker only', set_prefix=prefix, set_index=10)
    assert ProjectWrapper(scope_project).questions == []
    export = export_for(scope_project)
    assert export.get_dataset_indices() == [10]
    assert read_metadata(export, 10).metadata.title == 'Marker only'


def test_custom_attribute_uris_preserve_nested_dataset_scope(scope_project):
    page = add_page(scope_project, 'project/dataset/id', collection=True)
    middle = add_questionset(page)
    add_question(middle, 'project/dataset/description')
    for path in ('project/dataset/id', 'project/dataset/description'):
        attribute = add_attribute(path)
        attribute.uri_prefix = 'https://custom.example.test/terms'
        attribute.save()
    for index in (1, 10):
        add_answer(scope_project, 'project/dataset/id', f'Dataset {index}', set_index=index)
        add_answer(scope_project, 'project/dataset/description', f'Resource {index}', set_prefix=str(index))
    export = export_for(scope_project)
    assert export.get_dataset_indices() == [1, 10]
    assert read_metadata(export, 1).metadata.resource.value == 'Resource 1'
    assert read_metadata(export, 10).metadata.resource.value == 'Resource 10'


def test_multiple_questionset_levels_use_outermost_first_coordinates(scope_project):
    page = add_page(scope_project, 'project/dataset/id', collection=True)
    middle = add_questionset(page)
    creators = add_questionset(middle, 'project/dataset/creator/name', collection=True)
    inner = add_questionset(creators)
    add_question(inner, 'project/dataset/creator/given_name')
    add_question(inner, 'project/dataset/creator/family_name')
    for dataset in (1, 10):
        add_answer(scope_project, 'project/dataset/id', f'Dataset {dataset}', set_index=dataset)
        for group in (3, 7):
            prefix = f'{dataset}|0|{group}'
            add_answer(scope_project, 'project/dataset/creator/given_name', f'Person {dataset}-{group}',
                       set_prefix=prefix)
            add_answer(scope_project, 'project/dataset/creator/family_name', 'Example', set_prefix=prefix)
    # A non-collection intermediate coordinate must be zero.
    add_answer(scope_project, 'project/dataset/creator/given_name', 'Wrong middle', set_prefix='1|2|3')
    export = export_for(scope_project)
    for dataset in (1, 10):
        assert [creator.given_name for creator in read_metadata(export, dataset).metadata.creators] == [
            f'Person {dataset}-3', f'Person {dataset}-7',
        ]


def test_reused_questionset_retains_each_catalog_placement(scope_project):
    page = add_page(scope_project, 'project/dataset/id', collection=True)
    shared_set = add_questionset(page)
    add_question(shared_set, 'project/dataset/description')
    middle = add_questionset(page)
    attach_questionset(middle, shared_set)
    add_answer(scope_project, 'project/dataset/id', 'Dataset one', set_index=1)
    add_answer(scope_project, 'project/dataset/id', 'Dataset ten', set_index=10)
    add_answer(scope_project, 'project/dataset/description', 'Shallow placement', set_prefix='1')
    add_answer(scope_project, 'project/dataset/description', 'Deep placement', set_prefix='10|0')
    export = export_for(scope_project)
    assert read_metadata(export, 1).metadata.resource.value == 'Shallow placement'
    assert read_metadata(export, 10).metadata.resource.value == 'Deep placement'


def test_catalog_project_with_no_values_has_no_datasets(scope_project):
    add_page(scope_project, 'project/dataset/id', collection=True)
    export = export_for(scope_project)
    assert export.get_dataset_indices() == []
    assert read_metadata(export, 0).metadata.title is None


@pytest.mark.xfail(reason='RDMO filter_set uses an unbounded startswith prefix; upstream scoping gap',
                   raises=AssertionError, strict=False)
def test_core_filter_set_respects_dataset_prefix_boundary(scope_project):
    page = add_page(scope_project, 'project/dataset/id', collection=True)
    add_question(page, 'project/dataset/description')
    marker = add_answer(scope_project, 'project/dataset/id', 'Dataset one', set_index=1)
    for index in (1, 10):
        add_answer(scope_project, 'project/dataset/description', f'Resource {index}', set_prefix=str(index))
    values = scope_project.values.all().filter_set(marker).filter(attribute__path='project/dataset/description')
    assert set(values.values_list('set_prefix', flat=True)) == {'1'}


def test_mapping_context_accepts_prepared_values_without_export_or_queries(db, django_assert_num_queries):
    title = Value(attribute=Attribute(path='project/dataset/title'), text='Injected title', set_index=10)
    with django_assert_num_queries(0):
        context = RDMOReadContext(values={'project/dataset/title': [title]}, placements={}, set_index=10)
        assert compute_metadata(context).metadata.title == 'Injected title'
        assert context.shared().values is context.values
        assert context.group('', 10).issues is context.issues


@pytest.mark.parametrize('count', [2, 50, 100])
def test_value_queries_are_constant_across_datasets(scope_project, count, django_assert_num_queries):
    page = add_page(scope_project, 'project/dataset/id', collection=True)
    middle = add_questionset(page)
    add_question(middle, 'project/dataset/description')
    for index in range(count):
        add_answer(scope_project, 'project/dataset/id', f'Dataset {index}', set_index=index)
        add_answer(scope_project, 'project/dataset/description', f'Resource {index}', set_prefix=str(index))
    export = export_for(scope_project)
    with CaptureQueriesContext(connection) as queries:
        read_metadata(export, 0)
    table = connection.ops.quote_name(Value._meta.db_table)
    assert sum(f'FROM {table}' in query['sql'] for query in queries) == 1
    with django_assert_num_queries(0):
        for index in range(count):
            assert read_metadata(export, index).metadata.resource.value == f'Resource {index}'
        assert export.get_dataset_indices() == list(range(count))
