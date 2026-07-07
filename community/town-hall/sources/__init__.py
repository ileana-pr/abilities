import os
import importlib
import inspect
from .base import CivicSource

def discover_sources():
    """
    Automatically discovers and returns instances of all CivicSource 
    subclasses found in this directory.
    """
    sources = []
    # Path to the current directory
    pkg_dir = os.path.dirname(__file__)
    
    for filename in os.listdir(pkg_dir):
        if filename.endswith(".py") and filename not in ("__init__.py", "base.py"):
            module_name = f".{filename[:-3]}"
            # Import the module relatively
            try:
                module = importlib.import_module(module_name, package=__package__)
                
                # Look for classes that inherit from CivicSource
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, CivicSource) and 
                        obj is not CivicSource):
                        sources.append(obj())
            except Exception as e:
                print(f"Error loading source from {filename}: {e}")
                
    return sources
