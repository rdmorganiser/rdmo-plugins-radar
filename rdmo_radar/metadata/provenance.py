"""Optional mapping sidecars and bindings to the actual serialized output."""

import logging
import re
from dataclasses import replace
from xml.etree import ElementTree

from .types import MappingAttempt, MappingSource

MISSING = object()
ELEMENTS_NS = 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements'
DATASET_NS = 'http://radar-service.eu/schemas/descriptive/radar/v09/radar-dataset'
OUTCOMES = {'mapped', 'defaulted', 'empty', 'skipped', 'rejected', 'untraced'}
logger = logging.getLogger(__name__)


def metadata_value(metadata, path):
    value = metadata
    try:
        for name, index in re.findall(r'([^\.\[\]]+)|\[(\d+)\]', path):
            value = value[int(index)] if index else getattr(value, name)
        return value
    except (AttributeError, IndexError, TypeError):
        return MISSING


def pointer_value(data, path):
    if not isinstance(path, str) or (path and not path.startswith('/')) or re.search(r'~(?![01])', path):
        return MISSING
    try:
        for part in path.split('/')[1:]:
            part = part.replace('~1', '/').replace('~0', '~')
            if isinstance(data, list):
                if not part.isdigit() or (len(part) > 1 and part.startswith('0')):
                    return MISSING
                data = data[int(part)]
            else:
                data = data[part]
        return data
    except (KeyError, IndexError, TypeError):
        return MISSING


def json_leaves(data, path=''):
    """Yield JSON pointers and scalar values, including None, omitting empty objects and arrays."""
    if isinstance(data, dict):
        for key, value in data.items():
            key = str(key).replace('~', '~0').replace('/', '~1')
            yield from json_leaves(value, f'{path}/{key}')
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from json_leaves(value, f'{path}/{index}')
    else:
        yield path, data


def normalize_xml_path(path):
    return '/'.join(
        part if not part or part.startswith('@') or '[' in part or part == 'radar:radarDataset' else f'{part}[1]'
        for part in path.split('/')
    )


def xml_leaves(xml_data):
    root = ElementTree.fromstring(xml_data)

    def visit(node, path):
        if not len(node) and node.text is not None:
            yield path, node.text
        for name, value in node.attrib.items():
            yield f'{path}/@{name}', value
        counts = {}
        for child in node:
            name = child.tag.replace(f'{{{ELEMENTS_NS}}}', 're:').replace(f'{{{DATASET_NS}}}', 'radar:')
            counts[name] = counts.get(name, 0) + 1
            yield from visit(child, f'{path}/{name}[{counts[name]}]')

    return dict(visit(root, '/radar:radarDataset'))


def record_binding(record_output, field, path, value, reason=''):
    """Record a serializer binding without letting optional tracing interrupt export."""
    if record_output is None:
        return
    try:
        record_output(field, path, value, reason)
    except Exception as error:
        logger.warning('Could not record RADAR output provenance: error_type=%s', type(error).__name__)
        try:
            # A failed recorder invalidates the entire optional sidecar.
            record_output(None, '', None, '')
        except Exception:
            pass


def project_provenance(provenance, metadata, events, output, *, xml=False):
    if provenance is None or any(field is None for field, _, _, _ in events):
        return None
    leaves = xml_leaves(output) if xml else dict(json_leaves(output))
    normalize = normalize_xml_path if xml else lambda path: path
    bindings = {}
    generated = {}
    for field, path, value, reason in events:
        key = normalize(path)
        expected = str(value) if xml else value
        if key in leaves and leaves[key] == expected:
            bindings.setdefault(field, []).append((key, leaves[key]))
            if field.startswith('$'):
                generated[key] = reason
    rows = []
    covered = set()
    for attempt in provenance:
        if attempt.unsuccessful:
            rows.append(attempt)
            continue
        current = metadata_value(metadata, attempt.field)
        matches = bindings.get(attempt.field, ()) if current is not MISSING and current == attempt.value else ()
        if not matches:
            rows.append(
                replace(
                    attempt,
                    outcome='skipped',
                    output_path=None,
                    output_value=None,
                    reason='Value replaced or not emitted in this format',
                )
            )
        else:
            for path, value in matches:
                rows.append(replace(attempt, output_path=path, output_value=value))
                covered.add(path)
    for path, value in leaves.items():
        if path not in covered:
            reason = generated.get(path)
            if xml and path.endswith('/@schemeURI'):
                reason = 'Renderer identifier scheme URI'
            rows.append(
                MappingAttempt(
                    path,
                    (MappingSource('RADAR serializer', value),) if reason else (),
                    value,
                    'defaulted' if reason else 'untraced',
                    reason or 'No provenance supplied for this output field',
                    path,
                    value,
                )
            )
    return tuple(rows)


def validate_payload_provenance(provenance, payload):
    if provenance is None:
        return None
    rows = tuple(provenance)
    covered = set()
    for row in rows:
        if (
            not isinstance(row, MappingAttempt)
            or row.outcome not in OUTCOMES
            or not isinstance(row.field, str)
            or not all(isinstance(source, MappingSource) for source in row.sources)
        ):
            raise ValueError('Invalid provenance record.')
        if not row.unsuccessful:
            value = pointer_value(payload, row.output_path)
            if value is MISSING or value != row.output_value:
                raise ValueError('Provenance does not match the returned payload.')
            covered.add(row.output_path)
    rows += tuple(
        MappingAttempt(
            path,
            value=value,
            outcome='untraced',
            reason='No provenance supplied for this output field',
            output_path=path,
            output_value=value,
        )
        for path, value in json_leaves(payload)
        if path not in covered
    )
    return rows
