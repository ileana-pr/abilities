from .richmond_va import RichmondCitySource
from .virginia_state import VirginiaStateSource


def discover_sources():
    """return all registered civic sources.
    to add a locality: implement CivicSource in a new module, then append
    an instance below — no auto-import (openhome forbids importlib)."""
    return [
        VirginiaStateSource(),
        RichmondCitySource(),
    ]
