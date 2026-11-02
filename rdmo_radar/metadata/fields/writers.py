"""Stage field values at explicit destinations, without profile-specific coordinates."""

from collections.abc import Callable

from .contracts import Destination


def write_text(context, value, *, destination: Destination, target):
    context.add(destination.attribute, value, **destination.coordinates.kwargs())


def write_option(context, value, *, destination: Destination, option_map, target):
    """Import crosswalks map canonical values to explicitly chosen RDMO Options."""
    if value is None:
        return
    option = option_map.get(value)
    if option is None:
        context.warn(target, 'RADAR controlled value has no RDMO mapping', value)
        return
    context.add_option(destination.attribute, value, {option: value}, **destination.coordinates.kwargs())


def write_texts(context, values, *, destination: Callable[[int], Destination], target):
    for index, value in enumerate(values):
        write_text(context, value, destination=destination(index), target=f'{target}[{index}]')
