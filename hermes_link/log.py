from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import datetime
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


def format_event(event: dict[str, Any], *, color: bool = False) -> str:
    kind = event.get("event", "event")
    prefix = f"{_format_timestamp(event.get('ts'))} [{_short_thread(event)}]"
    if kind == "message":
        arrow = _paint(f"{event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "36", color)
        return (
            f"{_paint(prefix, '90', color)} {_paint('├─', '34', color)} {arrow}: "
            f"{event.get('body', '')}"
        )
    if kind == "final":
        agent = _paint(f"{event.get('agent', '?')} final", "32", color)
        return f"{_paint(prefix, '90', color)} {_paint('└─', '32', color)} {agent}: {event.get('body', '')}"
    if kind == "bridge_request":
        arrow = _paint(f"bridge {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "33", color)
        return (
            f"{_paint(prefix, '90', color)} {_paint('┌─', '33', color)} {arrow}: "
            f"{event.get('body', '')}"
        )
    return json.dumps(event, sort_keys=True)


def _format_timestamp(value: Any) -> str:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    return "0000-00-00 00:00:00"


def _short_thread(event: dict[str, Any]) -> str:
    thread = str(event.get("thread_id") or event.get("source_session_id") or "-")
    if len(thread) <= 12:
        return thread
    return thread[-12:]


def _paint(value: str, code: str, enabled: bool) -> str:
    if not enabled:
        return value
    return f"\033[{code}m{value}\033[0m"
