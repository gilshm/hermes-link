from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def default_state_dir(repo_root: Path) -> Path:
    return repo_root / ".hermes-link"


def default_log_path(repo_root: Path) -> Path:
    return default_state_dir(repo_root) / "events.jsonl"


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, event: str, **fields: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": time.time(),
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, sort_keys=True) + "\n")


def iter_events(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        yield json.loads(line)


def format_event(event: dict[str, Any]) -> str:
    kind = event.get("event", "event")
    if kind == "message":
        return (
            f"{event.get('from_agent', '?')} -> {event.get('to_agent', '?')}: "
            f"{event.get('body', '')}"
        )
    if kind == "final":
        return f"{event.get('agent', '?')} final: {event.get('body', '')}"
    if kind == "bridge_request":
        return (
            f"bridge {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}: "
            f"{event.get('body', '')}"
        )
    return json.dumps(event, sort_keys=True)
