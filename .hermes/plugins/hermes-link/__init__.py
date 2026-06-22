"""Hermes plugin bridge for Hermes Link."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROUTE_MESSAGE_SCHEMA = {
    "name": "route_message",
    "description": "Send or hand off a message to another Hermes Link org agent and return its response.",
    "parameters": {
        "type": "object",
        "properties": {
            "from_agent": {
                "type": "string",
                "description": "Your current agent id, for example agent_a.",
            },
            "to": {
                "type": "string",
                "description": "Target agent id from config/org.yaml, for example agent_b.",
            },
            "body": {
                "type": "string",
                "description": "The full message to deliver to the target agent.",
            },
            "mode": {
                "type": "string",
                "enum": ["send", "handoff"],
                "description": "Use send to ask the target for help. Use handoff when the target should take over and answer the user directly. Defaults to send.",
            },
            "max_messages": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum routed messages for this exchange. Defaults to 4.",
            },
        },
        "required": ["from_agent", "to", "body"],
    },
}


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="route_message",
        toolset="hermes-link",
        schema=ROUTE_MESSAGE_SCHEMA,
        handler=lambda args, **kwargs: _route_message(args, **kwargs),
        description="Route a message to another Hermes Link org agent.",
    )


def _route_message(args: dict[str, Any], **kwargs: Any) -> str:
    repo_root = _resolve_repo_root()
    python = repo_root / ".venv" / "bin" / "python"
    python_command = str(python) if python.exists() else "python3"
    payload = dict(args)
    if kwargs.get("session_id") and not payload.get("source_session_id"):
        payload["source_session_id"] = kwargs["session_id"]

    completed = subprocess.run(
        [python_command, "-m", "hermes_link.bridge_runner"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HERMES_LINK_HOME": str(repo_root)},
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"Hermes Link routing failed: {detail}")
    return completed.stdout.strip()


def _resolve_repo_root() -> Path:
    configured = os.environ.get("HERMES_LINK_HOME")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    marker = Path(__file__).resolve().parent / "repo_root.txt"
    if marker.exists():
        candidates.append(Path(marker.read_text(encoding="utf-8").strip()))
    candidates.append(Path(__file__).resolve().parents[3])

    for candidate in candidates:
        if (candidate / "hermes_link").is_dir():
            return candidate
    raise RuntimeError("Unable to locate Hermes Link repo. Set HERMES_LINK_HOME.")
