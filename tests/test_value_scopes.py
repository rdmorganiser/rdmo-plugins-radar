"""Catalog-aware behavior contracts, independent of the answer access implementation."""
import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
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

from rdmo_radar.factories import build_xml_export_service
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.values import model_key

from .helpers import add_answer, add_attribute, add_namespaced_attribute, export_for, read_metadata


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
        context = ProjectReadContext(values={'project/dataset/title': [title]}, placements={}, set_index=10)
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


def test_prepared_attribute_access_distinguishes_namespaces_without_queries(db, django_assert_num_queries):
    project = Project.objects.create(title='No catalog')
    attributes = [add_namespaced_attribute('research/title', prefix)
                  for prefix in ('https://first.test', 'https://second.test')]
    answers = [Value.objects.create(project=project, attribute=attribute, text=f'Title {index}')
               for index, attribute in enumerate(attributes)]
    with django_assert_num_queries(1):
        context = build_xml_export_service(project).reader(0).shared()
    with django_assert_num_queries(0):
        assert context.get_values('research/title') == []
        assert context.get_text('research/title') is None
        assert len(context.issues) == 1
        assert context.issues[0].reason == 'Ambiguous Attribute'
        for attribute, answer in zip(attributes, answers, strict=True):
            assert context.get_values_by_uri(attribute.uri) == [answer]
            assert context.get_values_by_attribute_id(attribute.pk) == [answer]
            assert context.get_text(attribute.uri) == answer.text
            assert context.get_values(attribute) == [answer]
        assert context.get_values('absent') == []
        assert context.get_values_by_uri('https://absent.test/domain/research/title') == []
        assert context.get_values_by_attribute_id(-1) == []
        assert len(context.issues) == 1


def test_unrelated_installed_attribute_does_not_make_project_path_ambiguous(db, django_assert_num_queries):
    project = Project.objects.create(title='No catalog')
    attribute = add_namespaced_attribute('research/title', 'https://first.test')
    unrelated = add_namespaced_attribute('research/title', 'https://second.test')
    other = Project.objects.create(title='Other')
    Value.objects.create(project=other, attribute=unrelated, text='Other project')
    answer = Value.objects.create(project=project, attribute=attribute, text='Selected project')
    context = build_xml_export_service(project).reader(0).shared()
    with django_assert_num_queries(0):
        assert context.get_values('research/title') == [answer]
        assert context.issues == []


def test_catalog_only_attribute_participates_in_path_ambiguity(scope_project, django_assert_num_queries):
    page = add_page(scope_project)
    question = add_question(page, 'research/title')
    other = add_namespaced_attribute('research/title', 'https://other.test')
    empty = add_question(page, 'research/title')
    empty.attribute = other
    empty.save()
    answer = Value.objects.create(project=scope_project, attribute=question.attribute, text='Present')
    context = build_xml_export_service(scope_project).reader(0).shared()
    with django_assert_num_queries(0):
        assert context.get_values('research/title') == []
        assert context.get_values_by_uri(question.attribute.uri) == [answer]
        assert context.get_values_by_uri(other.uri) == []
        assert len(context.issues) == 1


def test_namespace_collisions_do_not_share_catalog_placements(scope_project):
    page = add_page(scope_project)
    first = add_question(page, 'research/value').attribute
    nested = add_questionset(page)
    question = add_question(nested, 'research/value')
    second = add_namespaced_attribute('research/value', 'https://other.test')
    question.attribute = second
    question.save()
    shallow = Value.objects.create(project=scope_project, attribute=first, text='Shallow')
    Value.objects.create(project=scope_project, attribute=first, text='Wrong depth', set_prefix='0')
    deep = Value.objects.create(project=scope_project, attribute=second, text='Deep', set_prefix='0')
    Value.objects.create(project=scope_project, attribute=second, text='Wrong depth')
    context = build_xml_export_service(scope_project).reader(0).shared()
    assert context.get_values_by_uri(first.uri) == [shallow]
    assert context.get_values_by_attribute_id(second.pk) == [deep]
    assert context.get_values('research/value') == []


def test_unsaved_uri_attributes_are_distinct_in_legacy_buckets():
    attributes = [Attribute(path='research/title', uri=f'https://{namespace}.test/domain/research/title')
                  for namespace in ('first', 'second')]
    values = [Value(attribute=attribute, text=str(index)) for index, attribute in enumerate(attributes)]
    context = ProjectReadContext({'research/title': values}, {}, scope='project')
    assert context.get_values('research/title') == []
    for attribute, value in zip(attributes, values, strict=True):
        assert context.get_values_by_uri(attribute.uri) == [value]
        assert context.get_values(attribute) == [value]


def test_uri_less_unsaved_attributes_keep_explicit_object_identity():
    attributes = [Attribute(path='research/title'), Attribute(path='research/title')]
    values = [Value(attribute=attribute, text=str(index)) for index, attribute in enumerate(attributes)]
    context = ProjectReadContext({model_key(attribute): [value]
                               for attribute, value in zip(attributes, values, strict=True)}, {}, scope='project')
    assert context.get_values('research/title') == []
    for attribute, value in zip(attributes, values, strict=True):
        assert context.get_values(attribute) == [value]


def test_legacy_path_only_fixture_bucket_retains_scalar_diagnostics():
    values = [Value(attribute=Attribute(path='research/title'), text=text) for text in ('First', 'Second')]
    context = ProjectReadContext({'research/title': values}, {}, scope='project')
    assert context.get_values('research/title') == values
    assert context.get_text('research/title') is None
    assert [issue.reason for issue in context.issues] == ['Multiple answers for a scalar field']


def test_explicit_option_uris_do_not_collapse_equal_paths(db, django_assert_num_queries):
    project = Project.objects.create(title='Project')
    attribute = add_attribute('research/type')
    options = [Option.objects.create(uri_prefix=f'https://{namespace}.test', uri_path='type/example')
               for namespace in ('first', 'second')]
    for index, option in enumerate(options):
        Value.objects.create(project=project, attribute=attribute, option=option, collection_index=index)
    context = build_xml_export_service(project).reader(0).shared()
    with django_assert_num_queries(0):
        assert context.get_option('research/type', {'type/example': 'Example'}) is None
        assert any(issue.reason == 'Ambiguous Option path' for issue in context.issues)
        context.issues.clear()
        assert context.get_option(attribute.uri, {option.uri: 'Example' for option in options}) == 'Example'
        assert context.issues == []
        assert context.get_option(attribute.pk, {options[0].uri: 'First', options[1].uri: 'Second'}) is None
        assert [issue.reason for issue in context.issues] == ['Unmapped or conflicting controlled answers']


def test_unrelated_installed_options_do_not_make_read_mapping_ambiguous(db):
    project = Project.objects.create(title='Project')
    attribute = add_attribute('research/type')
    options = [Option.objects.create(uri_prefix=f'https://{namespace}.test', uri_path='type/example')
               for namespace in ('first', 'second')]
    Value.objects.create(project=project, attribute=attribute, option=options[0])
    context = build_xml_export_service(project).reader(0).shared()
    assert context.get_option('research/type', {'type/example': 'Example'}) == 'Example'
    assert context.issues == []


def test_catalogless_discovery_preserves_flat_markers_and_does_not_invent_datasets(db):
    project = Project.objects.create(title='No catalog')
    export = export_for(project)
    assert export.get_dataset_indices() == []
    for index in (1, 10):
        add_answer(project, 'project/dataset/title', f'Dataset {index}', set_index=index)
    export = export_for(project)
    assert export.get_dataset_indices() == [1, 10]
    assert read_metadata(export, 10).metadata.title == 'Dataset 10'


def test_ambiguous_dataset_markers_are_not_combined(db):
    project = Project.objects.create(title='Project')
    for index, namespace in enumerate(('first', 'second')):
        attribute = add_namespaced_attribute('project/dataset/title', f'https://{namespace}.test')
        Value.objects.create(project=project, attribute=attribute, text='Dataset', set_index=index)
    export = export_for(project)
    assert export.get_dataset_indices() == []
    context = export.get_service().reader(0)
    assert context.get_values('project/dataset/title') == []
    assert [issue.reason for issue in context.issues] == ['Ambiguous Attribute']


def test_explicit_identity_access_honors_snapshots(db, django_assert_num_queries):
    from rdmo.projects.models import Snapshot

    project = Project.objects.create(title='Project')
    snapshot = Snapshot.objects.create(project=project, title='Earlier')
    live = add_answer(project, 'research/title', 'Live')
    saved = add_answer(project, 'research/title', 'Saved', snapshot=snapshot)
    current = build_xml_export_service(project).reader(0).shared()
    previous = build_xml_export_service(project, snapshot=snapshot).reader(0).shared()
    with django_assert_num_queries(0):
        assert current.get_values_by_attribute_id(live.attribute_id) == [live]
        assert previous.get_values_by_uri(saved.attribute.uri) == [saved]


def test_exact_uri_dataset_reads_keep_distinct_nested_anchor_identities(scope_project):
    first_page = add_page(scope_project, 'project/dataset/id', collection=True)
    first_description = add_question(first_page, 'project/dataset/description').attribute
    second_page = add_page(scope_project)
    second_set = add_questionset(second_page, 'project/dataset/id', collection=True)
    second_set.attribute = add_namespaced_attribute('project/dataset/id', 'https://other.test')
    second_set.save()
    second_question = add_question(second_set, 'project/dataset/description')
    second_description = add_namespaced_attribute('project/dataset/description', 'https://other.test')
    second_question.attribute = second_description
    second_question.save()
    for index in (1, 10):
        Value.objects.create(project=scope_project, attribute=first_description,
                             text=f'Shallow {index}', set_index=index)
        Value.objects.create(project=scope_project, attribute=second_description,
                             text=f'Deep {index}', set_prefix='0', set_index=index)
    context = build_xml_export_service(scope_project).reader(1)
    assert context.get_text(first_description.uri) == 'Shallow 1'
    assert context.get_text(second_description.uri) == 'Deep 1'
    assert context.issues == []


def test_option_path_ambiguity_is_scoped_to_selected_answers():
    attribute = Attribute(path='project/dataset/language')
    values = [Value(attribute=attribute, option=Option(uri=f'https://{namespace}.test/options/language/example',
                                                     uri_path='language/example'), text='Selected', set_index=index)
              for namespace, index in (('first', 1), ('second', 10))]
    context = ProjectReadContext({attribute.path: values}, {}, set_index=1)
    assert context.get_option(attribute.path, {'language/example': 'eng'}) == 'eng'
    assert context.issues == []
    assert context.shared().get_option(attribute.path, {'language/example': 'eng'}) is None
    assert any(issue.reason == 'Ambiguous Option path' for issue in context.issues)


def test_specialized_template_framework_option_mapping_reports_namespace_collisions():
    path = 'project/dataset/creation_methods'
    attribute = Attribute(path=path)
    from rdmo_radar.metadata.constants import XMLVocabulary

    option_path = next(iter(XMLVocabulary.data_source_options))
    values = [Value(attribute=attribute, option=Option(uri=f'https://{namespace}.test/options/{option_path}',
                                                     uri_path=option_path), text=namespace)
              for namespace in ('first', 'second')]
    result = compute_metadata(ProjectReadContext({path: values}, {}))
    assert [source.resource_type for source in result.metadata.data_sources] == ['Other', 'Other']
    assert any(issue.reason == 'Ambiguous Option path' for issue in result.issues)


def test_model_identity_selection_and_diagnostics_do_not_load_deferred_fields(db, django_assert_num_queries):
    project = Project.objects.create(title='Project')
    attribute = add_attribute('research/title')
    for index, text in enumerate(('First', 'Second')):
        Value.objects.create(project=project, attribute=attribute, text=text, collection_index=index)
    selector = Attribute.objects.only('pk').get(pk=attribute.pk)
    context = build_xml_export_service(project).reader(0).shared()
    with django_assert_num_queries(0):
        assert [value.text for value in context.get_values(selector)] == ['First', 'Second']
        assert context.get_text(selector) is None
        assert context.issues[0].source == str(attribute.pk)
    assert 'uri' in selector.get_deferred_fields()


def test_template_framework_datasets_keep_repeated_nested_indices_and_result_coordinates(
    scope_project, django_assert_num_queries,
):
    from rdmo_radar.factories import build_export_service
    from rdmo_radar.mappings.template_framework import TEMPLATE_FRAMEWORK_MAPPING

    outer = add_page(scope_project, 'research/record', collection=True)
    dataset = add_questionset(outer, 'project/dataset/id', collection=True)
    fields = add_questionset(dataset)
    for path in ('project/dataset/title', 'project/dataset/description', 'project/dataset/radar_id',
                 'project/dataset/radar_url'):
        add_question(fields, path)
    for parent in (1, 10):
        add_answer(scope_project, 'project/dataset/id', f'Marker {parent}', set_prefix=str(parent), set_index=3)
        add_answer(scope_project, 'project/dataset/title', f'Dataset {parent}', set_prefix=f'{parent}|3')
        add_answer(scope_project, 'project/dataset/description', f'Resource {parent}', set_prefix=f'{parent}|3')
        add_answer(scope_project, 'project/dataset/radar_url', f'https://radar.test/old-{parent}',
                   set_prefix=f'{parent}|3')
    service = build_export_service(scope_project)
    with django_assert_num_queries(0):
        datasets = TEMPLATE_FRAMEWORK_MAPPING.get_datasets(scope_project, service.reader)
        assert [dataset.key for dataset in datasets] == ['dataset:1|3', 'dataset:10|3']
        assert [dataset.label for dataset in datasets] == ['Dataset 1', 'Dataset 10']
        assert [dataset.radar_url for dataset in datasets] == [
            'https://radar.test/old-1', 'https://radar.test/old-10',
        ]
        for dataset, parent in zip(datasets, (1, 10), strict=True):
            mapped = service.mapping(service.reader(dataset))
            assert mapped.metadata.title == f'Dataset {parent}'
            assert mapped.metadata.resource.value == f'Resource {parent}'
            assert mapped.issues == ()
    service.store_result(datasets[1], 'confirmed', 'https://radar.test/confirmed')
    assert scope_project.values.get(attribute__path='project/dataset/radar_id').set_prefix == '10|3'
    assert scope_project.values.get(attribute__path='project/dataset/radar_id').set_index == 0
    assert scope_project.values.get(attribute__path='project/dataset/radar_url', set_prefix='1|3').text == (
        'https://radar.test/old-1'
    )
    assert scope_project.values.get(attribute__path='project/dataset/radar_url', set_prefix='10|3').text == (
        'https://radar.test/confirmed'
    )


@pytest.mark.parametrize('native_ids', [False, True])
def test_primary_key_scope_matching_survives_stale_attribute_labels(native_ids):
    from rdmo_radar.metadata.values import model_key

    current = Attribute(pk=17, path='research/title', uri='https://current.test/domain/research/title')
    cached = Attribute(pk=17, path='research/title', uri='https://old.test/domain/research/title')
    answer = Value(attribute=current, text='Correct coordinate')
    wrong = Value(attribute=current, text='Wrong coordinate', set_prefix='0')
    values = {current.pk if native_ids else model_key(current): [answer, wrong]}
    if native_ids:
        values[None] = [Value(attribute=None, text='Unattached')]
    context = ProjectReadContext(values,
                              {model_key(cached): (((None, False),),)}, scope='project')
    assert context.get_values_by_attribute_id(17) == [answer]
    assert context.get_values_by_uri(current.uri) == [answer]
    assert context.get_values('research/title') == [answer]
    assert context.get_values_by_uri(cached.uri) == []
    assert context.issues == []
