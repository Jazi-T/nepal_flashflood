"""Project configuration loading utilities."""

from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML project configuration file."""
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)

