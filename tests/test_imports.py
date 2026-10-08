from types import SimpleNamespace
from xml.etree import ElementTree

from rdmo.domain.models import Attribute

from rdmo_radar.metadata.funding import merge_funding
from rdmo_radar.metadata.rdmo import RDMOWriteContext
from rdmo_radar.metadata.types import FundingReference, Identifier
from rdmo_radar.metadata.xml import parse_xml


def make_context(existing=None):
    existing = existing or []
    project = SimpleNamespace(values=SimpleNamespace(
        filter=lambda **kwargs: [
            value for value in existing if value.attribute.path == kwargs['attribute__path']
        ]
    ))
    paths = {
        'project/funder/id',
        'project/funder/name',
        'project/funder/grant_nr',
        'project/funder/programme/url',
        'project/funder/programme/title',
        'project/funder/name_identifier',
    }
    attributes = {path: Attribute(path=path) for path in paths}
    plugin = SimpleNamespace(
        current_project=project,
        values=[],
        get_attribute=lambda uri: attributes.get(uri.removeprefix(
            'https://rdmorganiser.github.io/terms/domain/')),
        get_option=lambda uri: None,
    )
    return RDMOWriteContext(plugin, dataset_index=0)


def test_funder_identifier_uses_rddm_type_attribute():
    root = ElementTree.fromstring('''
        <radarDataset xmlns="http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements">
          <fundingReferences><fundingReference>
            <funderName>Example Funder</funderName>
            <funderIdentifier type="ROR">https://ror.org/123</funderIdentifier>
          </fundingReference></fundingReferences>
        </radarDataset>
    ''')

    reference = parse_xml(root).funding_references[0]

    assert reference.funder_identifier == Identifier('https://ror.org/123', 'ROR')


def test_funder_identifier_is_reported_instead_of_written_to_set_marker():
    context = make_context()
    reference = FundingReference(
        funder_name='Example Funder',
        funder_identifier=Identifier('https://ror.org/123', 'ROR'),
    )

    merge_funding(context, [reference])

    marker = next(value for value in context.import_plugin.values if value.attribute.path == 'project/funder/id')
    assert marker.text == 'Example Funder'
    assert not any(value.attribute.path == 'project/funder/name_identifier' for value in context.import_plugin.values)
    assert context.issues[0].field == 'funderIdentifier'


def test_conflicting_existing_funding_value_is_preserved_with_warning():
    context = make_context()
    merge_funding(context, [FundingReference(funder_name='Example Funder', award_number='ABC-123')])
    merge_funding(context, [FundingReference(funder_name='Example Funder', award_number='DIFFERENT')])

    awards = [
        value.text for value in context.import_plugin.values
        if value.attribute.path == 'project/funder/grant_nr'
    ]
    assert awards == ['ABC-123']
    assert any(issue.field == 'project/funder/grant_nr' for issue in context.issues)
