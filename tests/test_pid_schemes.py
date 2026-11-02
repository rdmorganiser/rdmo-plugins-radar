"""PID schemes, pasted resolver URLs and field-specific identifier policies."""

from dataclasses import FrozenInstanceError, replace

import pytest

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from rdmo_radar.metadata.api import to_api_payload
from rdmo_radar.metadata.fields import (
    AffiliationSources,
    FundingSources,
    GroupSpec,
    IdentifierSource,
    PersonSources,
    Source,
    read_funding,
    read_keywords,
    read_people,
)
from rdmo_radar.metadata.normalization import normalize_answer, normalize_identifier
from rdmo_radar.metadata.pids import BUILTIN_PID_SCHEMES, GND, ORCID, ROR, PIDScheme, detect_pid
from rdmo_radar.metadata.read_context import ProjectReadContext
from rdmo_radar.metadata.types import Identifier, Keyword, RadarMetadata
from rdmo_radar.metadata.xml import ELEMENTS_NS, parse_xml, to_xml_payload

ORCID_ID = '0000-0002-1825-0097'
ORCID_URI = f'https://orcid.org/{ORCID_ID}'
ROR_URI = 'https://ror.org/0387prb75'
GND_URI = 'https://d-nb.info/gnd/4079154-3'


@pytest.mark.parametrize('scheme,bare,canonical', [
    (ORCID, ORCID_ID, ORCID_ID), (ROR, '0387prb75', ROR_URI), (GND, '4079154-3', GND_URI),
])
def test_schemes_preserve_canonical_identifiers_and_convert_to_uris(scheme, bare, canonical):
    expected = Identifier(canonical, scheme.name)
    uri = scheme.scheme_uri + bare
    for value in (bare, uri, uri.replace('https:', 'http:')):
        assert scheme.normalize(value) == expected
        assert scheme.as_uri(value) == uri
        assert normalize_identifier(value, scheme) == normalize_identifier(value, scheme.name) == expected
    assert normalize_identifier(uri) == expected
    assert normalize_identifier(bare) is None
    assert normalize_answer(f'Label {uri}', scheme=scheme) == normalize_answer(f'Label {uri}', scheme=scheme.name)
    assert scheme.normalize('invalid') is None
    assert scheme.as_uri('invalid') is None


@pytest.mark.parametrize('text', [
    '4079154-3', ORCID_ID, '0387prb75', 'https://example.test/4079154-3',
    'https://d-nb.info/gnd/', 'https://orcid.org/', 'https://ror.org/',
    'https://d-nb.info/not-gnd/4079154-3', f'{GND_URI}/extra', f'{GND_URI}?query=1',
    f'{GND_URI}#fragment', 'https://orcid.org.evil.test/' + ORCID_ID,
    'https://user@orcid.org/' + ORCID_ID, 'https://orcid.org:999/' + ORCID_ID,
    'https://[',
])
def test_detection_does_not_promote_bare_malformed_or_unrelated_values(text):
    assert detect_pid(text).matches == ()


@pytest.mark.parametrize('text', [
    GND_URI, f'Term ({GND_URI}).', f'Term [{GND_URI}],', f'"{GND_URI}"', f'<{GND_URI}>',
])
def test_detection_reports_exact_uri_spans(text):
    detected = detect_pid(text)
    assert detected.identifier == Identifier(GND_URI, 'GND')
    assert not detected.ambiguous
    assert len(detected.matches) == 1
    match = detected.matches[0]
    assert match.scheme is GND
    assert text[match.start:match.end] == GND_URI


def test_equivalent_matches_are_one_identity_but_distinct_identifiers_are_ambiguous():
    repeated = detect_pid(f'{GND_URI} {GND_URI.replace("https:", "http:")}')
    assert len(repeated.matches) == 2
    assert repeated.identifier == Identifier(GND_URI, 'GND')
    ambiguous = detect_pid(f'{GND_URI} {ORCID_URI}')
    assert ambiguous.ambiguous
    assert ambiguous.identifier is None


def test_embedded_pids_keep_labels_and_reconcile_html_and_external_ids():
    assert normalize_answer(f'Jane Doe ({ORCID_URI}).').label == 'Jane Doe'
    assert normalize_answer(f'Jane Doe {ORCID_URI}').identifier == Identifier(ORCID_ID, 'ORCID')
    answer = normalize_answer(f'Jane Doe <a href="{ORCID_URI}">ORCID</a> {ORCID_URI}', ORCID_ID)
    assert answer.label == 'Jane Doe'
    assert answer.identifier == Identifier(ORCID_ID, 'ORCID')
    assert not answer.issues
    assert normalize_answer(f'Institute {ROR_URI}', scheme='Other').identifier == Identifier(ROR_URI, 'ROR')
    mismatch = normalize_answer(f'Institute {ROR_URI}', scheme=ORCID)
    assert mismatch.identifier is None
    assert any('conflict' in issue.lower() for issue in mismatch.issues)
    external_conflict = normalize_answer(f'Term {GND_URI}', '4069254-0')
    assert external_conflict.identifier is None
    assert any('Conflicting' in issue for issue in external_conflict.issues)
    assert normalize_answer('Institute', ROR_URI, scheme='Other').identifier == Identifier(ROR_URI, 'ROR')
    assert normalize_answer('Term', 'https://example.test/term').issues == (
        'Unsupported or malformed external identifier',
    )


def test_builtin_schemes_and_registry_are_immutable():
    with pytest.raises(FrozenInstanceError):
        ORCID.name = 'Changed'
    with pytest.raises(TypeError):
        BUILTIN_PID_SCHEMES['Changed'] = ORCID


def context_for(**answers):
    paths, buckets = {}, {}
    for name, text in answers.items():
        uri = f'https://pid.test/domain/{name}'
        paths[name] = uri
        attribute = Attribute(uri=uri, path=name)
        buckets[uri] = [Value(attribute=attribute, text=text)]
    return ProjectReadContext(buckets, {}, provenance=[]), paths


@pytest.mark.parametrize('scheme', [None, 'Other', ROR, 'ROR'])
def test_identifier_source_promotes_resolver_urls_with_a_separate_name(scheme):
    context, paths = context_for(name='Institute', identifier=f'ROR: {ROR_URI}')
    sources = PersonSources(group=GroupSpec((paths['name'],)), name=paths['name'], identifiers=(
        IdentifierSource(paths['identifier'], scheme=scheme),
    ))
    people = read_people(context, sources=sources, target='creators')
    assert people[0].identifiers == [Identifier(ROR_URI, 'ROR')]
    assert context.issues == []
    assert any(row.reason == 'Detected resolver URL' for row in context.provenance)


def test_disabled_detection_and_explicit_conflicts_do_not_infer_a_scheme():
    context, paths = context_for(name='Institute', identifier=ROR_URI)
    sources = PersonSources(group=GroupSpec((paths['name'],)), name=paths['name'], identifiers=(
        IdentifierSource(paths['identifier'], detect_scheme=False),
    ))
    assert read_people(context, sources=sources, target='creators')[0].identifiers == []
    sources = replace(sources, identifiers=(IdentifierSource(paths['identifier'], scheme=ORCID),))
    assert read_people(context, sources=sources, target='creators')[0].identifiers == []
    assert any('conflicts' in issue.reason for issue in context.issues)


def test_disabled_detection_keeps_other_values_and_rejects_embedded_untyped_identity():
    context, paths = context_for(name='Institute', identifier=f'Registry {ROR_URI}')
    sources = PersonSources(group=GroupSpec((paths['name'],)), name=paths['name'], identifiers=(
        IdentifierSource(paths['identifier'], scheme='Other', detect_scheme=False),
    ))
    assert read_people(context, sources=sources, target='creators')[0].identifiers == [
        Identifier(f'Registry {ROR_URI}', 'Other'),
    ]


@pytest.mark.parametrize('choice,expected', [('Other', True), ('ROR', True), ('Unknown', False)])
def test_dynamic_scheme_selection_allows_other_promotion_but_not_invalid_choices(choice, expected):
    context, paths = context_for(name='Institute', identifier=ROR_URI, choice=choice)
    sources = PersonSources(group=GroupSpec((paths['name'],)), name=paths['name'], identifiers=(
        IdentifierSource(paths['identifier'], scheme_source=paths['choice'],
                         option_map={'other-option': 'Other', 'ror-option': 'ROR'}),
    ))
    people = read_people(context, sources=sources, target='creators')
    assert bool(people[0].identifiers) is expected


def test_affiliation_and_funding_sources_share_detection():
    context, paths = context_for(name='Jane Doe', institution='Institute', identifier=ROR_URI)
    sources = PersonSources(group=GroupSpec((paths['name'],)), name=paths['name'], affiliations=AffiliationSources(
        paths['institution'], IdentifierSource(paths['identifier'], scheme='Other'),
    ))
    person = read_people(context, sources=sources, target='creators')[0]
    assert person.affiliations[0].identifier == ROR_URI
    assert person.affiliations[0].identifier_scheme == 'ROR'
    context, paths = context_for(name='Institute', identifier=f'Registry {ROR_URI}')
    funding = read_funding(context, sources=FundingSources(
        group=GroupSpec((paths['name'],)), name=paths['name'], identifier=IdentifierSource(paths['identifier']),
    ), target='funding_references')
    assert funding[0].funder_identifier == Identifier(ROR_URI, 'ROR')


def test_refactor_preserves_reader_fallbacks_and_callback_string_arguments():
    context, paths = context_for(name='Jane Doe', identifier='malformed', institution='Institute', registry='malformed')
    sources = PersonSources(group=GroupSpec((paths['name'],)), name=paths['name'], identifiers=(
        IdentifierSource(paths['identifier'], scheme=ORCID),
    ), affiliations=AffiliationSources(paths['institution'], IdentifierSource(paths['registry'], scheme=ROR)))
    calls = []

    def callback(value, scheme=None):
        assert scheme is None or isinstance(scheme, str)
        calls.append(scheme)
        return normalize_identifier(value, scheme)

    person = read_people(context, sources=sources, target='creators', identifier_normalizer=callback)[0]
    assert person.identifiers == [Identifier('malformed', 'ORCID')]
    assert person.affiliations[0].identifier == 'malformed'
    assert {'ORCID', 'ROR'} <= set(calls)
    funding = read_funding(context, sources=FundingSources(
        group=GroupSpec((paths['name'],)), name=paths['name'],
        identifier=IdentifierSource(paths['registry'], scheme=ROR),
    ), target='funding_references')
    assert funding[0].funder_identifier is None


def test_custom_scheme_works_without_global_registration():
    class LocalScheme(PIDScheme):
        name = 'Local'
        scheme_uri = 'https://ids.test/'
        resolver_hosts = ('ids.test',)
        pattern = r'item-[0-9]+'

        def normalize(self, value):
            local = self._local_id(value)
            return Identifier(local, self.name, scheme_uri=self.scheme_uri) if local else None

    local = LocalScheme()
    assert 'Local' not in BUILTIN_PID_SCHEMES
    assert detect_pid('https://ids.test/item-1').identifier is None
    assert detect_pid('https://ids.test/item-1', schemes=(local,)).identifier == local.normalize('item-1')
    assert local.as_uri('item-1') == 'https://ids.test/item-1'
    assert normalize_answer('Label https://ids.test/item-1', scheme=local).identifier == local.normalize('item-1')
    context, paths = context_for(name='Institute', identifier='https://ids.test/item-1')
    sources = PersonSources(group=GroupSpec((paths['name'],)), name=paths['name'], identifiers=(
        IdentifierSource(paths['identifier'], scheme=local),
    ))
    assert read_people(context, sources=sources, target='creators')[0].identifiers == [local.normalize('item-1')]


@pytest.mark.parametrize('text,label', [(GND_URI, GND_URI), (f'Term ({GND_URI})', 'Term')])
def test_keyword_detection_exports_gnd_and_records_source_provenance(text, label):
    context, paths = context_for(keyword=text)
    keywords = read_keywords(context, sources=((Source(paths['keyword']), None),), target='keywords')
    assert keywords == [Keyword(label, 'GND', GND.scheme_uri, GND_URI, '4079154-3')]
    assert context.issues == []
    assert any(row.reason == 'Detected GND resolver URL' and row.sources for row in context.provenance)
    metadata = RadarMetadata(keywords=keywords)
    assert to_xml_payload(metadata)['keywords']['keyword'][0]['keywordScheme'] == 'GND'
    assert to_api_payload(metadata)['keywords']['keyword'][0]['valueURI'] == GND_URI


@pytest.mark.parametrize('text', [f'Term {ORCID_URI}', f'{GND_URI} {ORCID_URI}', 'Plain text'])
def test_unpromoted_keywords_retain_text_and_receive_other_scheme(text):
    context, paths = context_for(keyword=text)
    keywords = read_keywords(context, sources=((Source(paths['keyword']), None),), target='keywords')
    assert keywords == [text]
    metadata = RadarMetadata(keywords=keywords)
    assert to_xml_payload(metadata)['keywords']['keyword'] == [{'value': text, 'keywordScheme': 'Other'}]
    assert to_api_payload(metadata)['keywords']['keyword'] == [{'value': text, 'keywordScheme': 'OTHER'}]
    if text != 'Plain text':
        assert context.issues


@pytest.mark.parametrize('uri', [ORCID_URI, ROR_URI, GND_URI])
def test_pid_alone_does_not_establish_an_entity_name(uri):
    context, paths = context_for(name=uri)
    people = read_people(context, sources=PersonSources(
        group=GroupSpec((paths['name'],)), name=paths['name'],
    ), target='creators')
    assert people == []
    assert any('no usable' in issue.reason for issue in context.issues)


def test_other_only_xml_keywords_are_free_text_but_vocabulary_metadata_survives():
    from xml.etree import ElementTree

    root = ElementTree.fromstring(f'''<dataset xmlns="{ELEMENTS_NS}"><keywords>
      <keyword keywordScheme="Other">Free text</keyword>
      <keyword keywordScheme="Other" schemeURI="https://vocab.test/">Typed term</keyword>
    </keywords></dataset>''')
    assert parse_xml(root).keywords == ['Free text', Keyword('Typed term', 'Other', 'https://vocab.test/')]


def test_keyword_callbacks_keep_string_schemes_and_defaults_record_output_bindings():
    context, paths = context_for(keyword=f'Term {GND_URI}')
    hints = []

    def callback(text, external_id='', *, scheme=None):
        hints.append(scheme)
        return normalize_answer(text, external_id, scheme=scheme)

    read_keywords(context, sources=((Source(paths['keyword']), GND),), target='keywords', normalizer=callback)
    assert hints == ['GND']
    for serializer, expected in ((to_xml_payload, 'Other'), (to_api_payload, 'OTHER')):
        events = []
        serializer(RadarMetadata(keywords=['Free text']),
                   record_output=lambda *event, output=events: output.append(event))
        assert any(field == '$keywordScheme' and value == expected and reason == 'Free-text keyword scheme default'
                   for field, _, value, reason in events)
