from .base import CivicSource
from .richmond_va import RichmondCitySource
from .virginia_state import VirginiaStateSource


def discover_sources():
    """Return instances of all civic sources for Town Hall."""
    return [RichmondCitySource(), VirginiaStateSource()]
