from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from hermes_link.hermes_runner import HermesRunner
from hermes_link.log import EventLog
from hermes_link.org import load_org
from hermes_link.session_map import SessionMap


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        raise ValueError("usage: python -m hermes_link.handoff_runner <payload.json>")
    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    _run_handoff(payload)
    return 0


def _run_handoff(payload: dict[str, Any]) -> None:
    repo_root = Path(payload["repo_root"])
    state_dir = Path(payload["state_dir"])
    log_path = Path(payload["log_path"])
    from_agent = str(payload["from_agent"])
    to_agent = str(payload["to_agent"])
    body = str(payload["body"])
    max_messages = int(payload["max_messages"])
    source_session_id = str(payload.get("source_session_id") or "")
    thread_id = str(payload["thread_id"])

    org = load_org(repo_root / "config" / "org.yaml")
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
        event_log=EventLog(log_path),
        thread_id=thread_id,
    )
    runner.chat(
        to_agent,
        f"{from_agent} handed this conversation off to you:\n\n{body}\n\n"
        "You now own the conversation. Answer the original user directly. "
        "Do not send the answer back to the handing-off agent unless you need more help.",
        max_messages=max_messages,
    )
    if source_session_id:
        for agent, session_id in runner.sessions.items():
            if agent != from_agent:
                session_map.set(
                    source_session_id=source_session_id,
                    agent=agent,
                    target_session_id=session_id,
                )


if __name__ == "__main__":
    raise SystemExit(main())
