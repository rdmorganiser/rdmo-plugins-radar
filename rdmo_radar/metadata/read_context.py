"""Scoped access to prepared project Values and mapping diagnostics."""
from dataclasses import dataclass, field

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from .template_framework import ATTRIBUTE_TO_RADAR_FIELDS, get_dataset_values
from .types import MappingIssue
from .values import get_scoped_values, is_uri, model_key, prepare_read_data, selector_key, selector_label


@dataclass
class ProjectReadContext:
    """Read prepared project Values within a selected scope and collect diagnostics.

    Attribute arguments named ``path`` also accept full URIs, IDs, and models.
    The existing argument and field names remain compatible with custom mappings.
    """

    values: dict
    placements: dict
    set_prefix: str = ''
    set_index: int = 0
    scope: str = 'dataset'
    issues: list[MappingIssue] = field(default_factory=list)
    prepared: tuple | None = field(default=None, repr=False)
    dataset_prefix: str | None = None
    project: object | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.prepared is None:
            self.prepared = prepare_read_data(self.values, self.placements)

    def shared(self):
        return ProjectReadContext(
            self.values,
            self.placements,
            scope='project',
            issues=self.issues,
            prepared=self.prepared,
            project=self.project,
        )

    def group(self, prefix, index):
        return ProjectReadContext(
            self.values,
            self.placements,
            prefix,
            index,
            scope='group',
            issues=self.issues,
            prepared=self.prepared,
            project=self.project,
        )

    def resolve_attribute(self, selector):
        """Resolve only prepared project/catalog identities; never query installed models."""
        _, _, attribute_lookup_map = self.prepared
        attribute_keys = attribute_lookup_map.get(selector_key(selector), ())
        if len(attribute_keys) > 1:
            attribute_label = selector_label(selector)
            self.warn(
                attribute_label,
                attribute_label,
                'Ambiguous Attribute',
                '; '.join(sorted(attribute_key[3] or str(attribute_key[1]) for attribute_key in attribute_keys)),
            )
            return None
        return attribute_keys[0] if attribute_keys else None

    def groups(self, *paths):
        set_positions = {
            (value.set_prefix, value.set_index)
            for attribute_reference in paths
            for value in self.get_values(attribute_reference)
        }
        return [self.group(set_prefix, set_index) for set_prefix, set_index in sorted(set_positions)]

    def warn(self, target, source, reason, value=None):
        target = selector_label(target)
        source = selector_label(source)
        issue = MappingIssue(ATTRIBUTE_TO_RADAR_FIELDS.get(target, target), reason, value, source)
        if issue not in self.issues:
            self.issues.append(issue)

    def get_text(self, path: str | int | Attribute) -> str | None:
        texts = self.get_texts(path)
        if len(texts) > 1:
            self.warn(path, path, 'Multiple answers for a scalar field', '; '.join(texts))
            return None
        return texts[0] if texts else None

    def get_values(self, path: str | int | Attribute) -> list[Value]:
        attribute_key = self.resolve_attribute(path)
        if attribute_key is None:
            return []
        if self.scope == 'dataset':
            return get_dataset_values(self, attribute_key)
        attribute_values_map, attribute_placements_map, _ = self.prepared
        return get_scoped_values(
            attribute_values_map,
            attribute_placements_map,
            attribute_key,
            group=(self.set_prefix, self.set_index) if self.scope == 'group' else None,
        )

    def get_values_by_uri(self, uri: str) -> list[Value]:
        if not is_uri(uri):
            raise ValueError('Expected a full Attribute URI.')
        return self.get_values(uri)

    def get_values_by_attribute_id(self, attribute_id: int) -> list[Value]:
        return self.get_values(attribute_id)

    def get_texts(self, path: str | int | Attribute) -> list[str]:
        return list(
            dict.fromkeys(
                value.text.strip()
                for value in self.get_values(path)
                if value.text and value.text.strip() and not value.option
            )
        )

    def get_option(
        self,
        path: str | int | Attribute,
        options: dict[str, str],
        default: str | None = None,
    ) -> str | None:
        option_values = [value for value in self.get_values(path) if value.is_true]
        mapped_options = list(dict.fromkeys(self.map_options(path, options, values=option_values)))
        if option_values and (None in mapped_options or len(mapped_options) > 1):
            self.warn(path, path, 'Unmapped or conflicting controlled answers')
            return default
        return mapped_options[0] if mapped_options else default

    def map_options(self, path, options, *, values=None):
        """Map each Option by full URI, or an unambiguous legacy vocabulary path."""
        if values is None:
            values = self.get_values(path)
        option_identity_map = {}
        for value in values:
            if value.option is not None:
                option = value.option
                option_key = model_key(option, option.uri_path)
                option_identity_map.setdefault(option.uri_path, set()).add(option_key)
        mapped_options = []
        for value in values:
            option = value.option
            if option is None:
                mapped_options.append(None)
            elif option.uri and option.uri in options:
                mapped_options.append(options[option.uri])
            elif option.uri_path in options and len(option_identity_map[option.uri_path]) > 1:
                self.warn(path, path, 'Ambiguous Option path', option.uri_path)
                mapped_options.append(None)
            else:
                mapped_options.append(options.get(option.uri_path))
        return mapped_options

    def get_identifier(self, path):
        identifiers = list(
            dict.fromkeys(
                value.external_id or value.text for value in self.get_values(path) if value.external_id or value.text
            )
        )
        if len(identifiers) == 1 and '<' not in identifiers[0]:
            return identifiers[0]
        if identifiers:
            self.warn('nameIdentifier', path, 'Identifier is ambiguous or contains display markup')
        return None

