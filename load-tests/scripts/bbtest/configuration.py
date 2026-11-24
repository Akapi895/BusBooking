"""Resolve one test profile and explicit overrides before starting any services."""
import copy
from pathlib import Path

import yaml

from .common import validate_config


def merge(config, updates):
    result = copy.deepcopy(config)
    for key, value in updates.items():
        if isinstance(value, dict):
            result[key] = {**result.get(key, {}), **value}
        else:
            result[key] = value
    return result


def select(config_directory, mode="smoke", overrides=None):
    if mode not in ("smoke", "acceptance"):
        raise ValueError("Choose smoke or acceptance")
    directory = Path(config_directory)
    config = yaml.safe_load((directory / "acceptance.yaml").read_text(encoding="utf-8"))
    if mode == "smoke":
        config = merge(config, yaml.safe_load((directory / "smoke.yaml").read_text(encoding="utf-8")))
    return validate_config(merge(config, overrides or {}))
