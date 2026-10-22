"""Shared display helpers for XML and REST previews; no authentication or transport."""
import json

from rdmo.projects.models import Value


def compute_mapping_preview(provenance):
    return {
        'available': provenance is not None,
        'mapped': [row for row in provenance or () if not row.unsuccessful],
        'attempts': [row for row in provenance or () if row.unsuccessful],
    }


def compute_payload_field_path(payload, pointer):
    """Display a verified JSON pointer using dot notation and array indices."""
    path = ''
    value = payload
    for part in pointer.split('/')[1:]:
        key = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            path += f'[{key}]'
            value = value[int(key)]
        else:
            if key.isidentifier():
                path += ('.' if path else '') + key
            else:
                path += f'[{json.dumps(key, ensure_ascii=False)}]'
            value = value[key]
    return path or '$'


def compute_source_answers(values, mapping=None, *, payload=None):
    """Attach verified output locations to the exact native Values used by a mapping."""
    def value_key(value):
        return ('pk', value.pk) if value.pk is not None else ('object', id(value))

    fields = {}
    if mapping is not None and mapping['available']:
        for row in mapping['mapped']:
            if row.outcome not in ('mapped', 'defaulted') or not row.output_path:
                continue
            path = compute_payload_field_path(payload, row.output_path) if payload is not None else row.output_path
            for source in row.sources:
                if isinstance(source.value, Value):
                    destinations = fields.setdefault(value_key(source.value), [])
                    if path not in destinations:
                        destinations.append(path)
    return [{'value': value, 'radar_fields': fields.get(value_key(value), [])} for value in values]
