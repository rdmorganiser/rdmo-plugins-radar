"""Reusable compound writers; profiles supply destinations and merge policy."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .contracts import Destination
from .writers import write_option, write_text


@dataclass(frozen=True)
class IdentifierDestinations:
    value: Destination
    scheme: Destination | None = None
    scheme_options: Mapping = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, 'scheme_options', MappingProxyType(dict(self.scheme_options)))


@dataclass(frozen=True)
class AffiliationDestinations:
    name: Destination
    identifier: IdentifierDestinations | None = None
    scheme_uri: Destination | None = None


@dataclass(frozen=True)
class PersonDestinations:
    name: Destination
    given_name: Destination | None = None
    family_name: Destination | None = None
    name_type: Destination | None = None
    name_type_options: Mapping = field(default_factory=dict)
    contributor_type: Destination | None = None
    contributor_type_options: Mapping = field(default_factory=dict)
    identifiers: Callable[[int], IdentifierDestinations] | None = None
    affiliations: Callable[[int], AffiliationDestinations] | None = None

    def __post_init__(self):
        for name in ('name_type_options', 'contributor_type_options'):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True)
class FundingDestinations:
    funder_name: Destination
    funder_identifier: IdentifierDestinations | None = None
    award_number: Destination | None = None
    award_uri: Destination | None = None
    award_title: Destination | None = None


def _text(context, value, destination, target):
    if destination is not None:
        write_text(context, value, destination=destination, target=target)
    elif value:
        context.warn(target, 'No configured RDMO import destination', str(value))


def _option(context, value, destination, options, target):
    if destination is not None:
        write_option(context, value, destination=destination, option_map=options, target=target)
    elif value:
        context.warn(target, 'No configured RDMO import destination', value)


def write_identifier(context, value, *, destinations: IdentifierDestinations, target):
    if value is None:
        return
    write_text(context, value.value, destination=destinations.value, target=f'{target}.value')
    _option(
        context, value.identifier_type, destinations.scheme, destinations.scheme_options, f'{target}.identifier_type'
    )
    if value.scheme_uri or value.relation_type:
        context.warn(target, 'Identifier scheme URI/relation has no configured import destination')


def write_people(context, values, *, destinations, target):
    """destinations(index) supplies one person's fields and optional child factories."""
    for index, person in enumerate(values):
        spec = destinations(index)
        item = f'{target}[{index}]'
        for name in ('name', 'given_name', 'family_name'):
            _text(context, getattr(person, name), getattr(spec, name), f'{item}.{name}')
        for name in ('name_type', 'contributor_type'):
            _option(
                context, getattr(person, name), getattr(spec, name), getattr(spec, f'{name}_options'), f'{item}.{name}'
            )
        for child_index, identifier in enumerate(person.identifiers):
            if spec.identifiers is None:
                context.warn(f'{item}.identifiers', 'No configured RDMO import destination', identifier.value)
            else:
                write_identifier(
                    context,
                    identifier,
                    destinations=spec.identifiers(child_index),
                    target=f'{item}.identifiers[{child_index}]',
                )
        for child_index, affiliation in enumerate(person.affiliations):
            child_target = f'{item}.affiliations[{child_index}]'
            if spec.affiliations is None:
                context.warn(child_target, 'No configured RDMO import destination', affiliation.name)
                continue
            child = spec.affiliations(child_index)
            _text(context, affiliation.name, child.name, f'{child_target}.name')
            if affiliation.identifier:
                if child.identifier is None:
                    context.warn(child_target, 'No configured RDMO import destination', affiliation.identifier)
                else:
                    _text(context, affiliation.identifier, child.identifier.value, f'{child_target}.identifier')
                    _option(
                        context,
                        affiliation.identifier_scheme,
                        child.identifier.scheme,
                        child.identifier.scheme_options,
                        f'{child_target}.identifier_scheme',
                    )
            _text(context, affiliation.scheme_uri, child.scheme_uri, f'{child_target}.scheme_uri')


def write_funding(context, values, *, destinations, target):
    for index, reference in enumerate(values):
        spec = destinations(index)
        item = f'{target}[{index}]'
        for name in ('funder_name', 'award_number', 'award_uri', 'award_title'):
            _text(context, getattr(reference, name), getattr(spec, name), f'{item}.{name}')
        if reference.funder_identifier:
            if spec.funder_identifier is None:
                context.warn(
                    f'{item}.funder_identifier',
                    'No configured RDMO import destination',
                    reference.funder_identifier.value,
                )
            else:
                write_identifier(
                    context,
                    reference.funder_identifier,
                    destinations=spec.funder_identifier,
                    target=f'{item}.funder_identifier',
                )
