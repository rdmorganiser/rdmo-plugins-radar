"""Copy into your own RDMO plugin and configure its Attribute/Option URIs.

This example exports title, language and grouped creators, stages their imports,
and stores confirmed RADAR results. It uses no Template Framework configuration.
"""

from functools import partial

from rdmo_radar.exports import RadarCredentialsExportProvider, RadarExport, RadarExportProvider
from rdmo_radar.exports.storage import store_export_result
from rdmo_radar.imports import RadarImport
from rdmo_radar.mappings import ExportDataset, RadarMapping
from rdmo_radar.mappings.project import PROJECT_MAPPING
from rdmo_radar.metadata.builder import compute_metadata
from rdmo_radar.metadata.fields import (
    Coordinates,
    Destination,
    FieldMapping,
    GroupSpec,
    IdentifierDestinations,
    IdentifierSource,
    PersonDestinations,
    PersonSources,
    Source,
    read_language,
    read_people,
    read_text,
    write_option,
    write_people,
    write_text,
)
from rdmo_radar.metadata.importer import write_metadata
from rdmo_radar.metadata.write_context import ProjectWriteContext


def make_mapping(
    *,
    title,
    language,
    person_name,
    person_id,
    person_id_type,
    person_type,
    radar_id,
    radar_url,
    language_options,
    identifier_options,
    name_type_options,
    import_prefix='',
    person_prefix_suffix=(),
):
    """All selectors are full URIs; import crosswalks deliberately choose one Option per code."""
    language_import = {code: option for option, code in language_options.items()}
    identifier_import = {code: option for option, code in identifier_options.items()}
    name_type_import = {code: option for option, code in name_type_options.items()}
    people = PersonSources(
        group=GroupSpec((person_name,)),
        name=person_name,
        name_type=person_type,
        name_type_options=name_type_options,
        identifiers=(IdentifierSource(person_id, scheme_source=person_id_type, option_map=identifier_options),),
    )
    readers = {
        'title': partial(read_text, source=Source(title)),
        'language': partial(read_language, source=Source(language), option_map=language_options),
        'creators': partial(read_people, sources=people),
    }

    def build_reader(project, snapshot=None):
        read_project = PROJECT_MAPPING.build_reader(project, snapshot=snapshot)

        def read(dataset):
            root = read_project(None)
            if dataset is None:
                return root
            scope = dataset.scope
            return root.descendants(root.group(scope['prefix'], scope['index']), (title,))

        return read

    def get_datasets(project, reader):
        return [
            ExportDataset(
                f'{group.set_prefix}|{group.set_index}',
                group.get_text(title) or 'Untitled',
                {'prefix': group.set_prefix, 'index': group.set_index},
                radar_url=group.get_text(radar_url),
            )
            for group in reader(None).groups(title)
        ]

    def build_import_writer(plugin, *, set_index=None, existing_values, mapping=None):
        context = ProjectWriteContext(plugin, existing_values, Coordinates(set_prefix=import_prefix))
        if set_index is None:
            set_index = (
                max(
                    (value.set_index for value in context.get_values(title) if value.set_prefix == import_prefix),
                    default=-1,
                )
                + 1
            )
        position = Coordinates(import_prefix, set_index)

        def destination(attribute):
            return Destination(attribute, position)

        def person_destinations(index):
            prefix = '|'.join(filter(None, (import_prefix, str(set_index), *map(str, person_prefix_suffix))))
            child = Coordinates(prefix, index)
            return PersonDestinations(
                name=Destination(person_name, child),
                name_type=Destination(person_type, child),
                name_type_options=name_type_import,
                identifiers=lambda identifier_index: IdentifierDestinations(
                    Destination(person_id, Coordinates(prefix, index, identifier_index)),
                    Destination(person_id_type, Coordinates(prefix, index, identifier_index)),
                    identifier_import,
                ),
            )

        fields = FieldMapping(
            readers=readers,
            writers={
                'title': partial(write_text, destination=destination(title)),
                'language': partial(write_option, destination=destination(language), option_map=language_import),
                'creators': partial(write_people, destinations=person_destinations),
            },
        )
        return (
            partial(write_metadata, context, fields=fields)
            if mapping is None
            else partial(
                mapping,
                context,
                fields=fields,
            )
        )

    def store_result(project, dataset, identifier, url):
        scope = dataset.scope
        destinations = {
            name: {'uri': attribute, 'set_prefix': scope['prefix'], 'set_index': scope['index']}
            for name, attribute in (('radar_id', radar_id), ('radar_url', radar_url))
        }
        store_export_result(project, scope['index'], identifier, url, destinations=destinations)

    return RadarMapping(
        get_datasets,
        build_reader,
        partial(compute_metadata, fields=FieldMapping(readers=readers)),
        build_import_writer,
        store_result,
    )


CUSTOM_MAPPING = make_mapping(
    title='https://example.org/domain/records/title',
    language='https://example.org/domain/records/language',
    person_name='https://example.org/domain/records/authors/name',
    person_id='https://example.org/domain/records/authors/identifier',
    person_id_type='https://example.org/domain/records/authors/identifier_type',
    person_type='https://example.org/domain/records/authors/type',
    radar_id='https://example.org/domain/records/radar_id',
    radar_url='https://example.org/domain/records/radar_url',
    language_options={'https://example.org/options/languages/de': 'deu'},
    identifier_options={'https://example.org/options/identifiers/orcid': 'ORCID'},
    name_type_options={'https://example.org/options/names/person': 'Personal'},
)


class CustomXmlExport(RadarExport):
    mapping = CUSTOM_MAPPING


class CustomOAuthExport(RadarExportProvider):
    mapping = CUSTOM_MAPPING


class CustomCredentialsExport(RadarCredentialsExportProvider):
    mapping = CUSTOM_MAPPING


class CustomImport(RadarImport):
    mapping = CUSTOM_MAPPING
