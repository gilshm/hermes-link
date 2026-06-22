from __future__ import annotations

import json
import os
import subprocess
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
    to_agent = org.resolve_agent(_required(payload, "to"))
    body = _required(payload, "body")
    mode = str(payload.get("mode") or "send").strip()
    if mode not in {"send", "handoff"}:
        raise ValueError("mode must be send or handoff")
    max_messages = int(payload.get("max_messages") or 4)
    source_session_id = str(payload.get("source_session_id") or "").strip()
    thread_id = source_session_id or str(payload.get("thread_id") or "").strip() or "adhoc"
    state_dir = _state_dir(repo_root)
    event_log = EventLog(_log_path(repo_root, state_dir))
    if not org.can_route(from_agent, to_agent):
        denial = _policy_denial(from_agent, to_agent)
        event_log.write(
            "blocked",
            thread_id=thread_id,
            from_agent=from_agent,
            to_agent=to_agent,
            source_session_id=source_session_id,
            body=body,
            reason=denial,
        )
        print(denial)
        return 0
    event_log.write(
        "handoff" if mode == "handoff" else "bridge_request",
        thread_id=thread_id,
        from_agent=from_agent,
        to_agent=to_agent,
        source_session_id=source_session_id,
        body=body,
    )
    if mode == "handoff":
        _start_handoff_worker(
            repo_root=repo_root,
            state_dir=state_dir,
            log_path=_log_path(repo_root, state_dir),
            payload={
                "from_agent": from_agent,
                "to_agent": to_agent,
                "body": body,
                "max_messages": max_messages,
                "source_session_id": source_session_id,
                "thread_id": thread_id,
            },
        )
        print(
            "Handoff accepted. "
            f"Thread id: {thread_id}. "
            f"{to_agent} owns the conversation now. "
            "Do not summarize a target response; use the thread id to inspect completion."
        )
        return 0

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
    print(_format_transcript(result, final_agent=to_agent))
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


def _policy_denial(sender: str, recipient: str) -> str:
    return (
        "Hermes Link routing policy blocked this message: "
        f"{sender} is not allowed to send messages to {recipient}."
    )


def _format_transcript(result, *, final_agent: str) -> str:
    lines = ["Hermes Link transcript:"]
    for message in result.transcript[1:]:
        lines.append(f"{message.sender} -> {message.recipient}: {message.body}")
    lines.append(f"Final from {final_agent}: {result.final_response}")
    return "\n".join(lines)


def _start_handoff_worker(
    *,
    repo_root: Path,
    state_dir: Path,
    log_path: Path,
    payload: dict[str, Any],
) -> None:
    handoff_dir = state_dir / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    thread_id = str(payload["thread_id"])
    payload_path = handoff_dir / f"{_safe_filename(thread_id)}.json"
    stdout_path = handoff_dir / f"{_safe_filename(thread_id)}.out"
    stderr_path = handoff_dir / f"{_safe_filename(thread_id)}.err"
    payload_path.write_text(
        json.dumps(
            {
                **payload,
                "repo_root": str(repo_root),
                "state_dir": str(state_dir),
                "log_path": str(log_path),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with stdout_path.open("a", encoding="utf-8") as stdout_file, stderr_path.open("a", encoding="utf-8") as stderr_file:
        subprocess.Popen(
            [sys.executable, "-m", "hermes_link.handoff_runner", str(payload_path)],
            cwd=repo_root,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


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
