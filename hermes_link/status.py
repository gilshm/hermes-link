from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from hermes_link.org import AgentConfig


@dataclass(frozen=True)
class AgentStatus:
    agent: AgentConfig
    command_available: bool
    skill_installed: bool
    plugin_installed: bool
    plugin_enabled: bool | None


@dataclass(frozen=True)
class AgentHealth:
    agent: AgentConfig
    ok: bool
    response: str
    error: str
    elapsed_seconds: float


def inspect_agent(agent: AgentConfig, *, hermes_home: Path) -> AgentStatus:
    return AgentStatus(
        agent=agent,
        command_available=shutil.which(agent.command) is not None,
        skill_installed=(hermes_home / "profiles" / agent.name / "skills" / "agent-comms" / "SKILL.md").exists(),
        plugin_installed=(hermes_home / "profiles" / agent.name / "plugins" / "hermes-link" / "plugin.yaml").exists(),
        plugin_enabled=_plugin_enabled(agent.command),
    )


def check_agent_health(
    agent: AgentConfig,
    *,
    prompt: str = "Reply exactly: HERMES_LINK_HEALTH_OK",
    timeout: int = 30,
    cwd: Path | None = None,
) -> AgentHealth:
    command = shutil.which(agent.command)
    if command is None:
        return AgentHealth(agent=agent, ok=False, response="", error=f"command not found: {agent.command}", elapsed_seconds=0)

    start = time.monotonic()
    try:
        completed = subprocess.run(
            [agent.command, "chat", "-Q", "--safe-mode", "--ignore-rules", "--toolsets", "", "-q", prompt],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return AgentHealth(
            agent=agent,
            ok=False,
            response="",
            error=f"timed out after {timeout}s",
            elapsed_seconds=time.monotonic() - start,
        )

    elapsed = time.monotonic() - start
    response = _clean_health_output(completed.stdout)
    if completed.returncode != 0:
        return AgentHealth(
            agent=agent,
            ok=False,
            response=response,
            error=f"exit {completed.returncode}: {completed.stderr.strip()}",
            elapsed_seconds=elapsed,
        )
    return AgentHealth(agent=agent, ok=True, response=response, error="", elapsed_seconds=elapsed)


def _plugin_enabled(command: str) -> bool | None:
    if shutil.which(command) is None:
        return None
    completed = subprocess.run(
        [command, "plugins", "list", "--plain", "--no-bundled"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "enabled" and parts[-1] == "hermes-link":
            return True
    return False


def _clean_health_output(output: str) -> str:
    lines = [
        line
        for line in output.splitlines()
        if line.strip()
        and not line.startswith("session_id:")
        and "Resumed session " not in line
        and "tirith security scanner" not in line
    ]
    return "\n".join(lines).strip()


def yes_no(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"
