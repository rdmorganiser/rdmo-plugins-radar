"""Scoped access to prepared project Values and mapping diagnostics."""

from collections.abc import Callable
from dataclasses import dataclass, field

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from .types import MappingAttempt, MappingIssue, MappingSource
from .values import coordinates, is_uri, model_key, prepare_read_data, select_values, selector_key, selector_label


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
    scope: str = 'project'
    issues: list[MappingIssue] = field(default_factory=list)
    prepared: tuple | None = field(default=None, repr=False)
    dataset_prefix: str | None = None
    project: object | None = field(default=None, repr=False)
    value_selector: Callable | None = field(default=None, repr=False)
    field_names: dict[str, str] = field(default_factory=dict, repr=False)
    provenance: list[MappingAttempt] | None = field(default=None, repr=False)

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
            value_selector=self.value_selector,
            field_names=self.field_names,
            provenance=self.provenance,
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
            value_selector=self.value_selector,
            field_names=self.field_names,
            provenance=self.provenance,
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
        issue = MappingIssue(self.field_names.get(target, target), reason, value, source)
        if issue not in self.issues:
            self.issues.append(issue)

    def record_mapping(self, target, *, sources=(), value=None, outcome='mapped', reason=''):
        if self.provenance is not None and target is not None:
            sources = tuple(
                source
                if isinstance(source, MappingSource)
                else MappingSource(
                    source.attribute.uri or source.attribute.path,
                    source,
                )
                for source in sources
            )
            self.provenance.append(MappingAttempt(target, sources, value, outcome, reason))

    def record_empty_mapping(self, target, path):
        if target is None or self.provenance is None:
            return
        attribute_keys = self.prepared[2].get(selector_key(path), ())
        ambiguous = len(attribute_keys) > 1
        sources = (
            tuple(MappingSource(key[3] or str(key[1])) for key in attribute_keys)
            if ambiguous
            else (MappingSource(selector_label(path)),)
        )
        self.record_mapping(
            target,
            sources=sources,
            outcome='rejected' if ambiguous else 'empty',
            reason='Ambiguous Attribute' if ambiguous else 'No answer in this scope',
        )

    def _text_answers(self, path, target):
        values = self.get_values(path)
        answers = {}
        for value in values:
            if not value.text or not value.text.strip() or value.option:
                self.record_mapping(
                    target, sources=(value,), outcome='skipped', reason='Empty text or an Option answer'
                )
            elif value.text.strip() in answers:
                self.record_mapping(target, sources=(value,), outcome='skipped', reason='Duplicate normalized text')
            else:
                answers[value.text.strip()] = value
        if not answers:
            self.record_empty_mapping(target, path)
        return answers

    def get_text(self, path: str | int | Attribute, *, target=None) -> str | None:
        answers = self._text_answers(path, target)
        texts = list(answers)
        if len(texts) > 1:
            self.warn(path, path, 'Multiple answers for a scalar field', '; '.join(texts))
            self.record_mapping(
                target, sources=answers.values(), outcome='rejected', reason='Multiple answers for a scalar field'
            )
            return None
        if texts:
            self.record_mapping(target, sources=answers.values(), value=texts[0], reason='Normalized text')
        return texts[0] if texts else None

    def get_values(self, path: str | int | Attribute) -> list[Value]:
        attribute_key = self.resolve_attribute(path)
        if attribute_key is None:
            return []
        return (self.value_selector or select_values)(self, attribute_key)

    def get_scope_values(self) -> list[Value]:
        """Return prepared native Values in this scope without resolving ambiguous paths."""
        values = []
        for attribute_key in self.prepared[0]:
            values.extend((self.value_selector or select_values)(self, attribute_key))
        return sorted(
            values,
            key=lambda value: (
                value.attribute.path,
                value.attribute.uri or '',
                tuple(int(part) for part in coordinates(value)),
                value.collection_index,
            ),
        )

    def get_values_by_uri(self, uri: str) -> list[Value]:
        if not is_uri(uri):
            raise ValueError('Expected a full Attribute URI.')
        return self.get_values(uri)

    def get_values_by_attribute_id(self, attribute_id: int) -> list[Value]:
        return self.get_values(attribute_id)

    def get_texts(self, path: str | int | Attribute, *, target=None) -> list[str]:
        answers = self._text_answers(path, target)
        if target is not None:
            for index, (text, value) in enumerate(answers.items()):
                field_name = target.format(index=index) if '{index}' in target else f'{target}[{index}]'
                self.record_mapping(field_name, sources=(value,), value=text, reason='Normalized text')
        return list(answers)

    def get_option(
        self,
        path: str | int | Attribute,
        options: dict[str, str],
        default: str | None = None,
        *,
        target=None,
    ) -> str | None:
        values = self.get_values(path)
        option_values = [value for value in values if value.is_true]
        for value in values:
            if not value.is_true:
                self.record_mapping(target, sources=(value,), outcome='skipped', reason='Answer is not selected')
        mapped_options = list(dict.fromkeys(self.map_options(path, options, values=option_values)))
        if option_values and (None in mapped_options or len(mapped_options) > 1):
            self.warn(path, path, 'Unmapped or conflicting controlled answers')
            self.record_mapping(
                target, sources=option_values, outcome='rejected', reason='Unmapped or conflicting controlled answers'
            )
            if default is not None:
                self.record_mapping(target, value=default, outcome='defaulted', reason='Configured fallback')
            return default
        if option_values:
            self.record_mapping(
                target, sources=option_values, value=mapped_options[0], reason='Option vocabulary mapping'
            )
        else:
            self.record_empty_mapping(target, path)
            if default is not None:
                self.record_mapping(target, value=default, outcome='defaulted', reason='Configured default')
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

    def get_identifier(self, path, *, target=None):
        values = self.get_values(path)
        identifiers = list(
            dict.fromkeys(value.external_id or value.text for value in values if value.external_id or value.text)
        )
        if len(identifiers) == 1 and '<' not in identifiers[0]:
            self.record_mapping(
                target,
                sources=[value for value in values if value.external_id or value.text],
                value=identifiers[0],
                reason='External ID or answer text',
            )
            return identifiers[0]
        if identifiers:
            self.warn('nameIdentifier', path, 'Identifier is ambiguous or contains display markup')
            self.record_mapping(
                target, sources=values, outcome='rejected', reason='Identifier is ambiguous or contains display markup'
            )
        else:
            self.record_empty_mapping(target, path)
        return None
