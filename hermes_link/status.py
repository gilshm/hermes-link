from __future__ import annotations

import shutil
import subprocess
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


def inspect_agent(agent: AgentConfig, *, hermes_home: Path) -> AgentStatus:
    return AgentStatus(
        agent=agent,
        command_available=shutil.which(agent.command) is not None,
        skill_installed=(hermes_home / "profiles" / agent.name / "skills" / "agent-comms" / "SKILL.md").exists(),
        plugin_installed=(hermes_home / "profiles" / agent.name / "plugins" / "hermes-link" / "plugin.yaml").exists(),
        plugin_enabled=_plugin_enabled(agent.command),
    )


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


def yes_no(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"
