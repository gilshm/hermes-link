from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_HERMES_HOME = Path.home() / ".hermes"


def repo_root() -> Path:
    configured = os.environ.get("HERMES_LINK_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def state_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / ".hermes-link"


def runtime_config_path(root: Path | None = None) -> Path:
    return state_dir(root) / "config.json"


def load_runtime_config(root: Path | None = None) -> dict[str, Any]:
    path = runtime_config_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_runtime_config(root: Path | None = None, **fields: Any) -> Path:
    path = runtime_config_path(root)
    config = load_runtime_config(root)
    config.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def resolve_hermes_home(root: Path | None = None, explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get("HERMES_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    saved = load_runtime_config(root).get("hermes_home")
    if isinstance(saved, str) and saved.strip():
        return Path(saved).expanduser().resolve()
    return DEFAULT_HERMES_HOME.expanduser().resolve()
