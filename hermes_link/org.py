from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AgentConfig:
    name: str
    command: str
    expertise: str


@dataclass(frozen=True)
class OrgConfig:
    agents: dict[str, AgentConfig]
    skill_path: Path
    max_messages: int


def load_org(path: Path) -> OrgConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("org config must be a mapping")

    agents = _load_agents(raw.get("agents"))
    skill = raw.get("skill", "skills/agent-comms/SKILL.md")
    max_messages = int(raw.get("max_messages", 10))
    if max_messages < 1:
        raise ValueError("max_messages must be at least 1")

    return OrgConfig(
        agents=agents,
        skill_path=(path.parent.parent / str(skill)).resolve(),
        max_messages=max_messages,
    )


def _load_agents(raw: Any) -> dict[str, AgentConfig]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("org config must define at least one agent")

    agents: dict[str, AgentConfig] = {}
    for name, value in raw.items():
        if not isinstance(name, str):
            raise ValueError("agent ids must be strings")
        if not isinstance(value, dict):
            raise ValueError(f"agent {name} must be a mapping")
        command = value.get("command")
        if not isinstance(command, str) or not command:
            raise ValueError(f"agent {name} must define command")
        expertise = value.get("expertise", "")
        if not isinstance(expertise, str):
            raise ValueError(f"agent {name} expertise must be a string")
        agents[name] = AgentConfig(name=name, command=command, expertise=expertise.strip())
    return agents
