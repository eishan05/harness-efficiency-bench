"""Plugin registry loader."""

import importlib


def load_plugins(package_name):
    package = importlib.import_module(package_name)
    registry = {}
    for name in getattr(package, "__all__", []):
        module = importlib.import_module(f"{package_name}.{name}")
        if hasattr(module, "register"):
            module.register(registry)
    return registry
