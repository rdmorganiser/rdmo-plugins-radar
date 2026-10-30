"""The complete TF field assembly: selectors, crosswalks and policy choices."""

from dataclasses import replace
from functools import partial

from ...metadata.entities import prefer_name_source
from ...metadata.fields import (
    AffiliationSources,
    FieldMapping,
    FundingSources,
    GroupSpec,
    IdentifierSource,
    PersonSources,
    RoleSource,
    Source,
    read_data_sources,
    read_funding,
    read_keywords,
    read_language,
    read_names,
    read_people,
    read_resource,
    read_rights,
    read_software,
    read_subjects,
    read_text,
    read_texts,
)
from ...metadata.fields.people import report_orphan_identities
from ...metadata.normalization import normalize_primary_identifier
from ...metadata.types import GeoLocation, Identifier
from ...metadata.values import normalize
from . import dataset_writers as writers
from .crosswalks import (
    CREATION_METHOD_OPTIONS,
    DATA_MANAGEMENT_ROLE_OPTIONS,
    DATA_MANAGEMENT_ROLE_WARNINGS,
    PID_SYSTEM_OPTIONS,
    SOFTWARE_REQUIREMENT,
    SUBJECT_OPTIONS,
)
from .dataset_writers import LANGUAGE_PATH, RIGHTS_HOLDER_PATH
from .people_writers import merge_contributors, merge_funding, write_creators
from .vocabulary import XMLVocabulary

# Optional confirmed software Attributes. None retains the usage-requirement reader.
SOFTWARE_NAME_PATH = None
SOFTWARE_VERSION_PATH = None
RESOURCE_TYPE_PATH = None


def person_sources(base, *, scope='current', **kwargs):
    """TF naming conventions are configured here, never inferred by field getters."""
    names = tuple(f'{base}/{field}' for field in ('name', 'given_name', 'family_name'))
    return PersonSources(
        group=GroupSpec(names, scope),
        name=names[0],
        given_name=names[1],
        family_name=names[2],
        autocomplete=f'{base}/orcid-autocomplete',
        name_type=f'{base}/name_type',
        name_type_options=XMLVocabulary.name_type_options,
        default_name_type='Personal',
        identifiers=(
            IdentifierSource(
                f'{base}/name_identifier',
                scheme_source=f'{base}/name_identifier_scheme',
                option_map=XMLVocabulary.name_identifier_scheme_options,
            ),
            IdentifierSource(f'{base}/orcid', scheme='ORCID'),
            IdentifierSource(f'{base}/ror', scheme='ROR'),
        ),
        **kwargs,
    )


OWNER = person_sources(
    'project/dataset/owner',
    affiliations=AffiliationSources(
        'project/dataset/owner/organization/name',
        identifier=IdentifierSource(
            'project/dataset/owner/organization/name/identifier/value',
            scheme_source='project/dataset/owner/organization/name/identifier/type',
            option_map=XMLVocabulary.name_identifier_scheme_options,
        ),
    ),
)
CREATOR = person_sources(
    'project/dataset/creator', affiliations=AffiliationSources('project/dataset/creator/affiliation')
)
PARTNER = person_sources(
    'project/partner',
    scope='project',
    default_role='Other',
    affiliations=AffiliationSources(
        'project/partner/organization',
        identifier=IdentifierSource('project/partner/organization/ror', scheme='ROR'),
    ),
)
CONTRIBUTOR = replace(
    person_sources('project/contributor', scope='project', default_role='Other'),
    group=GroupSpec(
        (
            'project/contributor/name',
            'project/contributor/given_name',
            'project/contributor/family_name',
            'project/contributor/orcid-autocomplete',
        ),
        'project',
    ),
    name_type='project/contributor/person_or_entity',
    name_type_options={'partner-types/person': 'Personal', 'partner-types/entity': 'Organizational'},
    default_name_type=None,
    affiliations=AffiliationSources(
        'project/contributor/organization',
        identifier=IdentifierSource('project/contributor/organization/ror', scheme='ROR'),
        autocomplete='project/contributor/organization/ror-autocomplete',
    ),
    roles=(RoleSource('project/contributor/role'), RoleSource('dmp/contributor/role', require_shared_placement=True)),
    role_options=XMLVocabulary.contributor_type_options,
)
FUNDING = FundingSources(
    group=GroupSpec(
        (
            'project/funder/name',
            'project/funder/grant_nr',
            'project/funder/programme/title',
            'project/funder/programme/url',
        ),
        'project',
    ),
    name='project/funder/name',
    scheme='project/funder/id/type',
    option_map=XMLVocabulary.funder_identifier_scheme_options,
    award_number='project/funder/grant_nr',
    award_uri='project/funder/programme/url',
    award_title='project/funder/programme/title',
)

DATA_MANAGEMENT = PersonSources(
    group=GroupSpec(('project/data_management/name',), 'project'),
    name='project/data_management/name',
    identifiers=(IdentifierSource('project/data_management/orcid', scheme='ORCID'),),
    roles=(RoleSource('project/data_management/role'),),
    role_options=DATA_MANAGEMENT_ROLE_OPTIONS,
    role_warnings=DATA_MANAGEMENT_ROLE_WARNINGS,
    default_name_type='Personal',
    default_role='Other',
)


def _preferred_people(context, preferred, legacy, *, target):
    selected = preferred.group.context(context)
    if prefer_name_source(selected, preferred.group.anchors, legacy.group.anchors, target=target):
        return read_people(context, sources=preferred, target=target)
    report_orphan_identities(selected, preferred, target)
    return read_people(context, sources=legacy, target=target)


def read_contributors(context, *, target, include_data_management=False):
    people = _preferred_people(context, CONTRIBUTOR, PARTNER, target=target)
    shared = context.shared()
    if not include_data_management:
        if context.provenance is not None:
            paths = (DATA_MANAGEMENT.name, 'project/data_management/orcid', 'project/data_management/role')
            # Trace native answers without resolving or choosing between namespaces
            # for a source family that is disabled.
            answers = shared.get_scope_values()
            for path in paths:
                values = [v for v in answers if v.attribute.path == path and v.is_true
                          and (v.text or v.external_id or v.option)]
                if values:
                    shared.record_mapping(target, sources=values, outcome='skipped',
                                          reason='Data-management contributor mapping is disabled')
        return people
    trace_start = len(context.provenance) if context.provenance is not None else 0
    issue_start = len(context.issues)
    offset = len(people)
    additional = read_people(context, sources=DATA_MANAGEMENT, target=target, repeat_roles=True, start_index=offset)
    replacements = {}
    duplicates = set()
    for index, person in enumerate(additional, offset):
        identifiers = {(i.identifier_type, normalize(i.value)) for i in person.identifiers}
        match = next((position for position, existing in enumerate(people)
                      if existing == person or (
                          existing.contributor_type == person.contributor_type and identifiers.intersection(
                              (i.identifier_type, normalize(i.value)) for i in existing.identifiers
                          )
                      )), None)
        old = f'{target}[{index}]'
        if match is None:
            replacements[old] = f'{target}[{len(people)}]'
            people.append(person)
        else:
            replacements[old] = f'{target}[{match}]'
            duplicates.add(old)
            if people[match] != person:
                context.warn(target, DATA_MANAGEMENT.name,
                             'Existing contributor identity and role retained; differing details were not merged')

    def rebase(field):
        return next((new + field[len(old):] for old, new in replacements.items() if field.startswith(old)), field)

    if context.provenance is not None:
        context.provenance[trace_start:] = [
            replace(attempt, field=rebase(attempt.field), **(
                {'outcome': 'skipped', 'reason': 'Duplicate contributor identity and role; existing entry retained'}
                if not attempt.unsuccessful and any(attempt.field.startswith(old) for old in duplicates) else {}
            )) for attempt in context.provenance[trace_start:]
        ]
    context.issues[issue_start:] = [replace(issue, field=rebase(issue.field)) for issue in context.issues[issue_start:]]
    return people


def read_title(context, *, target):
    title = read_text(context, source=Source('project/dataset/title'), target=target)
    if not title:
        title = read_text(context, source=Source('project/dataset/id'), target=target)
        if title and context.provenance is not None:
            context.provenance[-1] = replace(
                context.provenance[-1], outcome='defaulted', reason='Dataset ID title fallback'
            )
    return title


def read_identifier(context, *, target):
    value = context.get_text('project/dataset/data_publication_pid', target=f'{target}.value')
    if not value:
        planned = context.get_values('project/dataset/pids/system')
        if planned:
            supplied = any(answer.text.strip() and answer.option is None
                           for answer in context.get_values('project/dataset/data_publication_pid'))
            context.record_mapping(
                f'{target}.identifier_type', sources=planned, outcome='skipped',
                reason=('Publication PID is unusable; identifier scheme not applied' if supplied
                        else 'Planned PID system; no existing publication PID supplied'),
            )
        else:
            context.record_empty_mapping(f'{target}.identifier_type', 'project/dataset/pids/system')
        return None
    kind = context.get_option(
        'project/dataset/pids/system',
        {path: kind for path, kind in {**XMLVocabulary.identifier_type_options, **PID_SYSTEM_OPTIONS}.items()
         if kind in XMLVocabulary.primary_identifier_types},
        target=f'{target}.identifier_type',
    )
    if value and kind not in XMLVocabulary.primary_identifier_types:
        reason = 'Primary identifier requires DOI, Handle or RADAR; identifier omitted'
        context.warn(target, 'project/dataset/pids/system', reason)
        context.record_mapping(
            f'{target}.value', sources=context.get_values('project/dataset/data_publication_pid'),
            outcome='rejected', reason=reason,
        )
        return None
    normalized = normalize_primary_identifier(value, kind)
    if normalized is None:
        reason = 'Primary identifier value is malformed or incompatible with the RADAR schema; identifier omitted'
        context.warn(target, 'project/dataset/data_publication_pid', reason, value)
        context.record_mapping(f'{target}.value', sources=context.get_values('project/dataset/data_publication_pid'),
                               outcome='rejected', reason=reason)
        return None
    if normalized != value:
        context.record_mapping(f'{target}.value', sources=context.get_values('project/dataset/data_publication_pid'),
                               value=normalized, reason='Normalized primary identifier resolver URL')
    return Identifier(normalized, kind)


def read_additional_titles(context, *, target):
    acronym = read_text(context, source=Source('project/acronym', 'project'), target=f'{target}[0]')
    return [acronym] if acronym else []


def read_geo_locations(context, *, target):
    region = read_text(
        context, source=Source('project/dataset/usage_technology/geo_location'), target=f'{target}[0].region'
    )
    return [GeoLocation(region=region)] if region else []


TF_FIELDS = FieldMapping(
    readers={
        'identifier': read_identifier,
        'title': read_title,
        'additional_titles': read_additional_titles,
        'keywords': partial(
            read_keywords,
            sources=(
                (Source('project/research_question/keywords', 'project'), None),
                (Source('project/research_question/keywords/gnd', 'project'), 'GND'),
            ),
        ),
        'publishers': partial(read_names, source=Source('project/dataset/curation/responsible_person/name')),
        'language': partial(read_language, source=Source(LANGUAGE_PATH), option_map=XMLVocabulary.language_options),
        'subject_areas': partial(
            read_subjects,
            source=Source('project/research_field/title', 'project'),
            option_map={**XMLVocabulary.controlled_subject_area_options, **SUBJECT_OPTIONS},
            uncertain_options=('research_fields/211',),
        ),
        'resource': partial(
            read_resource, source=Source('project/dataset/description'),
            type_source=Source(RESOURCE_TYPE_PATH) if RESOURCE_TYPE_PATH is not None else None,
            option_map=XMLVocabulary.resource_type_general_options,
        ),
        'geo_locations': read_geo_locations,
        'data_sources': partial(
            read_data_sources,
            source=Source('project/dataset/creation_methods'),
            option_map={**XMLVocabulary.data_source_options, **CREATION_METHOD_OPTIONS},
        ),
        'software': partial(
            read_software,
            source=Source(SOFTWARE_NAME_PATH or 'project/dataset/usage_technology'),
            option_map=None if SOFTWARE_NAME_PATH is not None else {SOFTWARE_REQUIREMENT: True},
            version_source=SOFTWARE_VERSION_PATH,
            software_type='Resource Viewing',
        ),
        'processing': partial(read_texts, source=Source('project/dataset/method')),
        'rights': partial(
            read_rights,
            source=Source('project/dataset/sharing/conditions'),
            option_map=XMLVocabulary.controlled_rights_options,
        ),
        'rights_holders': partial(read_names, source=Source(RIGHTS_HOLDER_PATH)),
        'creators': partial(_preferred_people, preferred=OWNER, legacy=CREATOR),
        'contributors': read_contributors,
        'funding_references': partial(read_funding, sources=FUNDING),
    },
    writers={
        'title': writers.write_title,
        'identifier': writers.write_identifier,
        'additional_titles': writers.write_additional_titles,
        'keywords': writers.write_keywords,
        'subject_areas': writers.write_subject_areas,
        'language': writers.write_language,
        'resource': writers.write_resource,
        'rights': writers.write_rights,
        'rights_holders': writers.write_rights_holders,
        'data_sources': writers.write_data_sources,
        'processing': writers.write_processing,
        'geo_locations': writers.write_geo_locations,
        'creators': write_creators,
        'contributors': merge_contributors,
        'funding_references': merge_funding,
    },
)
