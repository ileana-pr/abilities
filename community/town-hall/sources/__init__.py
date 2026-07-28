import importlib
import inspect
from pathlib import Path

from .base import CivicSource


def discover_sources() -> list[CivicSource]:
    """auto-discover all CivicSource subclasses in this directory.
    contributors add a new file here — no other registration needed."""
    sources: list[CivicSource] = []
    sources_dir = Path(__file__).parent
    for path in sorted(sources_dir.glob("*.py")):
        if path.stem in ("__init__", "base"):
            continue
        try:
            module = importlib.import_module(f".{path.stem}", package=__package__)
        except Exception:
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj is not CivicSource
                and issubclass(obj, CivicSource)
                and obj.__module__ == module.__name__
            ):
                sources.append(obj())
    return sources
