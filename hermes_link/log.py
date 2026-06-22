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


def trace_events(path: Path, thread_id: str) -> list[dict[str, Any]]:
    return [event for event in iter_events(path) if _matches_thread(event, thread_id)]


def format_event(event: dict[str, Any], *, color: bool = False) -> str:
    kind = event.get("event", "event")
    prefix = f"{_format_timestamp(event.get('ts'))} [{_short_thread(event)}]"
    if kind == "message":
        arrow = _paint(f"{event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "36", color)
        return (
            f"{_paint(prefix, '90', color)} {_paint('├─', '34', color)} {arrow}: "
            f"{event.get('body', '')}"
        )
    if kind == "handoff":
        arrow = _paint(f"handoff {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "33", color)
        return (
            f"{_paint(prefix, '90', color)} {_paint('╞═', '33', color)} {arrow}: "
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
    if kind == "scatter_start":
        recipients = ", ".join(event.get("recipients", []))
        sender = _paint(f"scatter {event.get('from_agent', '?')} -> [{recipients}]", "35", color)
        return f"{_paint(prefix, '90', color)} {_paint('┬─', '35', color)} {sender}"
    if kind == "scatter_message":
        arrow = _paint(f"scatter {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "35", color)
        return (
            f"{_paint(prefix, '90', color)} {_paint('├─', '35', color)} {arrow}: "
            f"{event.get('body', '')}"
        )
    if kind == "scatter_result":
        arrow = _paint(f"gather {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "32", color)
        return (
            f"{_paint(prefix, '90', color)} {_paint('├─', '32', color)} {arrow}: "
            f"{event.get('body', '')}"
        )
    if kind == "scatter_error":
        arrow = _paint(f"scatter failed {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "31", color)
        return f"{_paint(prefix, '90', color)} {_paint('!─', '31', color)} {arrow}: {event.get('reason', '')}"
    if kind == "blocked":
        arrow = _paint(f"blocked {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "31", color)
        return f"{_paint(prefix, '90', color)} {_paint('!─', '31', color)} {arrow}: {event.get('reason', '')}"
    return json.dumps(event, sort_keys=True)


def format_trace(events: list[dict[str, Any]], *, thread_id: str, color: bool = False) -> str:
    if not events:
        return f"No events found for trace: {thread_id}"

    lines = [f"Trace {thread_id}"]
    for index, event in enumerate(events):
        connector = "└─" if index == len(events) - 1 else "├─"
        lines.append(_format_trace_line(event, connector=connector, color=color))
    return "\n".join(lines)


def format_trace_mermaid(events: list[dict[str, Any]], *, thread_id: str) -> str:
    if not events:
        return f"%% No events found for trace: {thread_id}"

    participants = _trace_participants(events)
    lines = ["sequenceDiagram", f"    %% Trace {thread_id}"]
    for participant in participants:
        lines.append(f"    participant {_mermaid_id(participant)} as {participant}")
    for event in events:
        lines.extend(_format_mermaid_event(event))
    return "\n".join(lines)


def _format_timestamp(value: Any) -> str:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    return "0000-00-00 00:00:00"


def _short_thread(event: dict[str, Any]) -> str:
    thread = str(event.get("thread_id") or event.get("source_session_id") or "-")
    if len(thread) <= 12:
        return thread
    return thread[-12:]


def _matches_thread(event: dict[str, Any], thread_id: str) -> bool:
    candidates = [
        str(event.get("thread_id") or ""),
        str(event.get("source_session_id") or ""),
    ]
    return any(candidate == thread_id or candidate.endswith(thread_id) for candidate in candidates if candidate)


def _trace_participants(events: list[dict[str, Any]]) -> list[str]:
    participants: set[str] = set()
    for event in events:
        for key in ("from_agent", "to_agent", "agent"):
            value = event.get(key)
            if isinstance(value, str) and value:
                participants.add(value)
    return sorted(participants)


def _format_mermaid_event(event: dict[str, Any]) -> list[str]:
    kind = event.get("event")
    if kind == "bridge_request":
        return [_mermaid_message(event.get("from_agent"), event.get("to_agent"), f"bridge: {event.get('body', '')}", arrow="->>")]
    if kind == "message":
        return [_mermaid_message(event.get("from_agent"), event.get("to_agent"), event.get("body", ""), arrow="->>")]
    if kind == "handoff":
        return [_mermaid_message(event.get("from_agent"), event.get("to_agent"), f"handoff: {event.get('body', '')}", arrow="->>")]
    if kind == "scatter_start":
        recipients = ", ".join(event.get("recipients", []))
        return [f"    Note over {_mermaid_id(event.get('from_agent'))}: scatter to [{_mermaid_text(recipients)}]"]
    if kind == "scatter_message":
        return [_mermaid_message(event.get("from_agent"), event.get("to_agent"), event.get("body", ""), arrow="->>")]
    if kind == "scatter_result":
        return [_mermaid_message(event.get("from_agent"), event.get("to_agent"), event.get("body", ""), arrow="-->>")]
    if kind == "scatter_error":
        return [_mermaid_message(event.get("from_agent"), event.get("to_agent"), f"failed: {event.get('reason', '')}", arrow="-x")]
    if kind == "blocked":
        return [_mermaid_message(event.get("from_agent"), event.get("to_agent"), f"blocked: {event.get('reason', '')}", arrow="-x")]
    if kind == "final":
        agent = _mermaid_id(event.get("agent"))
        return [f"    Note over {agent}: final: {_mermaid_text(event.get('body', ''))}"]
    return [f"    Note over {_mermaid_id(event.get('agent') or event.get('from_agent') or 'unknown')}: {_mermaid_text(json.dumps(event, sort_keys=True))}"]


def _mermaid_message(sender: Any, recipient: Any, body: Any, *, arrow: str) -> str:
    return f"    {_mermaid_id(sender)}{arrow}{_mermaid_id(recipient)}: {_mermaid_text(body)}"


def _mermaid_id(value: Any) -> str:
    text = str(value or "unknown")
    return "".join(char if char.isalnum() else "_" for char in text)


def _mermaid_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text.replace("\\", "\\\\").replace(":", "#58;")


def _format_trace_line(event: dict[str, Any], *, connector: str, color: bool) -> str:
    timestamp = _paint(_format_timestamp(event.get("ts")), "90", color)
    connector = _paint(connector, "34", color)
    kind = event.get("event")
    if kind == "bridge_request":
        body = event.get("body", "")
        route = _paint(f"bridge {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "33", color)
        return f"{timestamp} {connector} {route}: {body}"
    if kind == "message":
        from_session = _session_suffix(event.get("from_session_id"))
        to_session = _session_suffix(event.get("to_session_id"))
        route = _paint(
            f"{event.get('from_agent', '?')}{from_session} -> {event.get('to_agent', '?')}{to_session}",
            "36",
            color,
        )
        return f"{timestamp} {connector} {route}: {event.get('body', '')}"
    if kind == "handoff":
        from_session = _session_suffix(event.get("from_session_id"))
        to_session = _session_suffix(event.get("to_session_id"))
        route = _paint(
            f"handoff {event.get('from_agent', '?')}{from_session} -> {event.get('to_agent', '?')}{to_session}",
            "33",
            color,
        )
        return f"{timestamp} {connector} {route}: {event.get('body', '')}"
    if kind == "scatter_start":
        recipients = ", ".join(event.get("recipients", []))
        route = _paint(f"scatter {event.get('from_agent', '?')} -> [{recipients}]", "35", color)
        return f"{timestamp} {connector} {route}"
    if kind == "scatter_message":
        to_session = _session_suffix(event.get("to_session_id"))
        route = _paint(
            f"scatter {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}{to_session}",
            "35",
            color,
        )
        return f"{timestamp} {connector} {route}: {event.get('body', '')}"
    if kind == "scatter_result":
        from_session = _session_suffix(event.get("from_session_id"))
        to_session = _session_suffix(event.get("to_session_id"))
        route = _paint(
            f"gather {event.get('from_agent', '?')}{from_session} -> {event.get('to_agent', '?')}{to_session}",
            "32",
            color,
        )
        return f"{timestamp} {connector} {route}: {event.get('body', '')}"
    if kind == "scatter_error":
        route = _paint(f"scatter failed {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "31", color)
        return f"{timestamp} {connector} {route}: {event.get('reason', '')}"
    if kind == "final":
        agent = _paint(f"{event.get('agent', '?')} final{_session_suffix(event.get('session_id'))}", "32", color)
        return f"{timestamp} {connector} {agent}: {event.get('body', '')}"
    if kind == "blocked":
        route = _paint(f"blocked {event.get('from_agent', '?')} -> {event.get('to_agent', '?')}", "31", color)
        return f"{timestamp} {connector} {route}: {event.get('reason', '')}"
    return f"{timestamp} {connector} {json.dumps(event, sort_keys=True)}"


def _session_suffix(value: Any) -> str:
    if not value:
        return ""
    session_id = str(value)
    return f"({session_id[-8:]})"


def _paint(value: str, code: str, enabled: bool) -> str:
    if not enabled:
        return value
    return f"\033[{code}m{value}\033[0m"
