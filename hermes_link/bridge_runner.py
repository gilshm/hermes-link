from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from hermes_link.hermes_runner import HermesRunner
from hermes_link.log import EventLog
from hermes_link.org import load_org
from hermes_link.session_map import SessionMap


def main() -> int:
    payload = json.loads(sys.stdin.read())
    repo_root = Path(os.environ.get("HERMES_LINK_HOME", Path.cwd())).resolve()
    org = load_org(repo_root / "config" / "org.yaml")

    from_agent = _required(payload, "from_agent")
    to_agent = _required(payload, "to")
    body = _required(payload, "body")
    max_messages = int(payload.get("max_messages") or 4)
    source_session_id = str(payload.get("source_session_id") or "").strip()
    thread_id = source_session_id or str(payload.get("thread_id") or "").strip() or "adhoc"
    state_dir = _state_dir(repo_root)
    event_log = EventLog(_log_path(repo_root, state_dir))
    event_log.write(
        "bridge_request",
        thread_id=thread_id,
        from_agent=from_agent,
        to_agent=to_agent,
        source_session_id=source_session_id,
        body=body,
    )
    session_map = SessionMap(state_dir / "session-map.json")
    sessions = {}
    if source_session_id:
        target_session_id = session_map.get(source_session_id=source_session_id, agent=to_agent)
        if target_session_id:
            sessions[to_agent] = target_session_id

    runner = HermesRunner(
        org,
        cwd=repo_root,
        sessions=sessions,
        event_log=event_log,
        thread_id=thread_id,
    )
    result = runner.chat(
        to_agent,
        f"{from_agent} sent you this message:\n\n{body}",
        max_messages=max_messages,
        stop_recipient=from_agent,
    )
    for message in result.transcript[1:]:
        print(f"{message.sender} -> {message.recipient}: {message.body}")
    print(result.final_response)
    if source_session_id:
        for agent, session_id in runner.sessions.items():
            if agent != from_agent:
                session_map.set(
                    source_session_id=source_session_id,
                    agent=agent,
                    target_session_id=session_id,
                )
    return 0


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing required field: {key}")
    return value.strip()


def _state_dir(repo_root: Path) -> Path:
    configured = os.environ.get("HERMES_LINK_STATE_DIR")
    if configured:
        return Path(configured)
    return repo_root / ".hermes-link"


def _log_path(repo_root: Path, state_dir: Path) -> Path:
    configured = os.environ.get("HERMES_LINK_LOG")
    if configured:
        return Path(configured)
    return state_dir / "events.jsonl"


if __name__ == "__main__":
    raise SystemExit(main())
