"""Composition and diagnostic contracts, independent of the RDMO adapters."""
from copy import deepcopy
from dataclasses import replace

import pytest

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.dataset import write_dataset_fields
from rdmo_radar.metadata.funding import merge_funding
from rdmo_radar.metadata.importer import write_metadata
from rdmo_radar.metadata.people import merge_contributors, write_creators
from rdmo_radar.metadata.types import (
    FundingReference,
    MappingIssue,
    MappingResult,
    PersonOrOrganization,
    RadarMetadata,
    Resource,
)
from rdmo_radar.metadata.xml import to_xml_payload

from .helpers import (
    configure_service,
    dataset_payload,
    make_import,
    make_read_context,
    read_metadata,
    template_framework_context,
)


@pytest.mark.parametrize('component, replacement, changes', [
    ('dataset', RadarMetadata(title='Custom', resource=Resource('Description')), {'title': 'Custom'}),
    ('creators', [PersonOrOrganization('Custom')], {'creators': [PersonOrOrganization('Custom')]}),
    ('contributors', [PersonOrOrganization('Custom')], {'contributors': [PersonOrOrganization('Custom')]}),
    ('funding', [FundingReference('Custom')], {'funding_references': [FundingReference('Custom')]}),
])
def test_reader_can_be_replaced_without_changing_other_fields(component, replacement, changes):
    baseline = compute_metadata(make_read_context())
    result = compute_metadata(make_read_context(), **{component: lambda context: replacement})

    assert result.metadata == replace(baseline.metadata, **changes)
    assert result.issues == baseline.issues == ()


def test_readers_run_in_order_and_snapshot_diagnostics():
    context = make_read_context()
    calls = []

    def dataset(ctx):
        assert ctx is context
        calls.append('dataset')
        ctx.warn('title', 'project/dataset/title', 'First warning')
        return RadarMetadata(title='Dataset')

    def people(ctx):
        assert ctx is context
        calls.append('people')
        ctx.warn('title', 'project/dataset/title', 'First warning')
        return [PersonOrOrganization('Person')]

    def funding(ctx):
        assert ctx is context
        calls.append('funding')
        ctx.warn('funding', 'project/funder/name', 'Second warning')
        return []

    result = compute_metadata(context, dataset=dataset, creators=people, contributors=people, funding=funding)
    assert calls == ['dataset', 'people', 'people', 'funding']
    assert [issue.reason for issue in result.issues] == ['First warning', 'Second warning']
    context.issues.clear()
    assert len(result.issues) == 2
    assert not hasattr(result.metadata, 'mapping_issues')
    assert to_api_payload(result.metadata)['title'] == 'Dataset'
    assert to_xml_payload(result.metadata)['title'] == 'Dataset'


def test_dataset_diagnostics_stay_with_their_results_and_export_files():
    context = make_read_context()
    context.values['project/dataset/title'].append(Value(
        attribute=Attribute(path='project/dataset/title'), text='Conflicting title',
    ))
    context.values['project/dataset/title'].append(Value(
        attribute=Attribute(path='project/dataset/title'), text='Second dataset', set_index=1,
    ))
    export = configure_service(RadarExport('radar', 'RADAR', 'rdmo_radar.exports.RadarExport'))
    configure_service(export, reader=lambda set_index: template_framework_context(context.values, set_index=set_index))

    first = read_metadata(export, 0)
    second = read_metadata(export, 1)
    assert first.metadata.title is None
    assert first.issues
    assert second.metadata.title == 'Second dataset'
    assert second.issues == ()
    dataset_payload(export, 0)
    dataset_payload(export, 1)
    assert not hasattr(export, 'mapping_issues')

    export.get_datasets = lambda: [0, 1]
    files = export.prepare_files()
    assert files[0]['mapping_issues'] == first.issues
    assert files[1]['mapping_issues'] == ()


@pytest.mark.parametrize('component, changed_paths', [
    ('dataset', {'project/dataset/title'}),
    ('creators', {'project/dataset/creator/name'}),
    ('contributors', {'project/partner/name'}),
    ('funding', {'project/funder/id', 'project/funder/name'}),
])
def test_writer_can_be_replaced_without_changing_other_staged_values(component, changed_paths):
    metadata = RadarMetadata(
        title='Dataset', resource=Resource('Description'), keywords=['Keyword'],
        creators=[PersonOrOrganization('Creator')], contributors=[PersonOrOrganization('Partner')],
        funding_references=[FundingReference('Funder', award_number='Award')],
    )
    original = deepcopy(metadata)
    baseline = make_import()
    assert write_metadata(baseline, metadata, 10) == ()

    def custom(context, data):
        if component == 'dataset':
            write_dataset_fields(context, replace(data, title='Custom'))
        elif component == 'creators':
            write_creators(context, [PersonOrOrganization('Custom')])
        elif component == 'contributors':
            merge_contributors(context, [PersonOrOrganization('Custom')])
        else:
            merge_funding(context, [FundingReference('Custom', award_number='Award')])

    plugin = make_import()
    assert write_metadata(plugin, metadata, 10, **{component: custom}) == ()

    def unchanged(values):
        return [(value.attribute.path, value.text, value.option, value.set_prefix,
                 value.set_index, value.collection_index) for value in values
                if value.attribute.path not in changed_paths]

    assert unchanged(plugin.values) == unchanged(baseline.values)
    assert {value.text for value in plugin.values if value.attribute.path in changed_paths} == {'Custom'}
    assert all(value.pk is None for value in plugin.values)
    assert metadata == original


def test_writers_run_in_order_and_return_only_a_diagnostic_snapshot():
    metadata = RadarMetadata(creators=[PersonOrOrganization('Creator')], contributors=[PersonOrOrganization('Partner')],
                             funding_references=[FundingReference('Funder')])
    calls = []
    contexts = []

    def writer(name, expected):
        def write(context, data):
            assert data is expected
            calls.append(name)
            contexts.append(context)
            context.warn(name, 'Custom warning')
            context.warn(name, 'Custom warning')
        return write

    issues = write_metadata(
        make_import(), metadata, 0,
        dataset=writer('dataset', metadata), creators=writer('creators', metadata.creators),
        contributors=writer('contributors', metadata.contributors),
        funding=writer('funding', metadata.funding_references),
    )
    assert calls == ['dataset', 'creators', 'contributors', 'funding']
    assert issues == tuple(MappingIssue(name, 'Custom warning') for name in calls)
    assert all(context is contexts[0] for context in contexts)
    contexts[0].issues.clear()
    assert len(issues) == 4
    assert not isinstance(issues, MappingResult)
