import io
import zipfile
from types import SimpleNamespace
from xml.etree import ElementTree

from rdmo_radar.exports.exports import RadarExport
from rdmo_radar.exports.providers import RadarExportProvider
from rdmo_radar.exports.renderers import RadarExportRenderer


def test_authorize_params_use_configured_client_id():
    provider = RadarExportProvider('radar', 'RADAR', 'rdmo_radar.exports.RadarExportProvider')

    assert provider.get_authorize_params(None, 'state')['client_id'] == 'configured-client-id'


def test_provider_form_validates_choices_and_escapes_export_link():
    form = RadarExportProvider.Form(
        dataset_choices=[('0', '<script>alert(1)</script>')],
        workspace_choices=[('workspace-1', 'Workspace')],
        radar_urls=['https://radar.example.test/dataset/?q="<script>'],
    )

    field_html = str(form['dataset'])
    assert '<script>' not in field_html
    assert '&lt;script&gt;' in field_html
    assert 'rel="noopener noreferrer"' in field_html

    invalid_form = RadarExportProvider.Form(
        data={'dataset': 'not-displayed', 'workspace': 'not-displayed'},
        dataset_choices=[('0', 'Dataset')],
        workspace_choices=[('workspace-1', 'Workspace')],
        radar_urls=[None],
    )
    assert not invalid_form.is_valid()


def test_dataset_resource_type_uses_standard_mapping():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    option_mappings = []

    export.get_set = lambda *args, **kwargs: []
    export.get_values = lambda *args, **kwargs: []
    export.get_list = lambda *args, **kwargs: []
    export.get_year = lambda *args, **kwargs: None
    export.get_text = lambda path, **kwargs: 'Resource' if path.endswith('/resource_type') else None

    def get_option(options, path, **kwargs):
        option_mappings.append(options)
        return 'Dataset'

    export.get_option = get_option

    dataset = export.get_dataset(0)

    assert dataset['resource'] == {'value': 'Resource', 'resourceType': 'Dataset'}
    assert export.resource_type_general_options in option_mappings
    assert export.data_source_options['radar_data_source/trial'] == 'Trial'
    assert export.data_source_options['radar_data_source/organism'] == 'Organism'
    assert export.data_source_options['radar_data_source/tissue'] == 'Tissue'


def test_structured_name_keeps_primary_name():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    values = {
        'project/dataset/creator/name': 'Doe, Jane',
        'project/dataset/creator/given_name': 'Jane',
        'project/dataset/creator/family_name': 'Doe',
    }
    export.get_text = lambda path, **kwargs: values.get(path)
    export.get_list = lambda *args, **kwargs: []
    export.get_option = lambda *args, **kwargs: None

    name = export.get_name('creator', 'project/dataset/creator')

    assert name['creatorName'] == 'Doe, Jane'
    assert name['givenName'] == 'Jane'
    assert name['familyName'] == 'Doe'


def test_renderer_preserves_structured_names_and_contributor_type(capsys):
    xml = RadarExportRenderer().render({
        'creators': {'creator': [{
            'creatorName': 'Doe, Jane',
            'givenName': 'Jane',
            'familyName': 'Doe',
        }]},
        'contributors': {'contributor': [{
            'contributorName': 'Smith, John',
            'givenName': 'John',
            'familyName': 'Smith',
            'contributorType': 'DATA_MANAGER',
        }]},
    })
    root = ElementTree.fromstring(xml)
    namespace = {'radar': 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'}

    assert root.findtext('.//radar:creatorName', namespaces=namespace) == 'Doe, Jane'
    contributor = root.find('.//radar:contributor', namespace)
    assert contributor.attrib['contributorType'] == 'DATA_MANAGER'
    assert contributor.findtext('radar:contributorName', namespaces=namespace) == 'Smith, John'
    assert capsys.readouterr().out == ''


def test_zip_export_is_complete_and_readable():
    export = RadarExport('radar-xml', 'RADAR XML', 'rdmo_radar.exports.RadarExport')
    export.project = SimpleNamespace(title='Project')
    export.get_set = lambda *args, **kwargs: [SimpleNamespace(set_index=0)]
    export.get_text = lambda path, **kwargs: 'dataset-id' if path.endswith('/id') else None
    export.get_dataset = lambda set_index: {'title': 'Dataset'}

    response = export.render()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['dataset-id.xml']
        assert b'<title>Dataset</title>' in archive.read('dataset-id.xml')
