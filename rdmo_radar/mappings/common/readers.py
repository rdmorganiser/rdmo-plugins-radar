"""Load an operation's answers once; profiles own context construction and scope."""
from ...metadata.values import fetch_catalog_placements, fetch_project_values, prepare_read_data


def prepare_project_read(project, snapshot=None):
    """Return loaded Values, catalog placements, and prepared identity lookups.

    Each reader factory calls this once and reuses the result across selections.
    Context selectors, diagnostic state, and coordinates remain profile choices.
    """
    values = fetch_project_values(project, snapshot)
    placements = fetch_catalog_placements(project.catalog)
    return values, placements, prepare_read_data(values, placements)
