from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


BUILT_IN_BROADCASTS = frozenset({"direct_reports", "manager", "peers", "team"})


@dataclass(frozen=True)
class AgentConfig:
    name: str
    command: str
    expertise: str
    title: str = ""
    team: str = ""
    manager: str = ""


@dataclass(frozen=True)
class TopicConfig:
    name: str
    default: str
    agents: tuple[str, ...]


@dataclass(frozen=True)
class GroupConfig:
    name: str
    agents: tuple[str, ...]


@dataclass(frozen=True)
class RoutingPolicy:
    mode: str


@dataclass(frozen=True)
class OrgConfig:
    agents: dict[str, AgentConfig]
    topics: dict[str, TopicConfig]
    groups: dict[str, GroupConfig]
    routing: RoutingPolicy
    skill_path: Path
    max_messages: int
    scatter_timeout: int

    def resolve_agent(self, target: str) -> str:
        normalized = target.removeprefix("@")
        if normalized in self.agents:
            return normalized
        if normalized in self.topics:
            return self.topics[normalized].default
        raise ValueError(f"unknown agent or topic: {target}")

    def resolve_group(self, target: str) -> tuple[str, ...]:
        normalized = target.removeprefix("@")
        if normalized not in self.groups:
            raise ValueError(f"unknown group: {target}")
        return self.groups[normalized].agents

    def resolve_broadcast(self, sender: str, target: str) -> tuple[str, ...]:
        normalized = target.removeprefix("@")
        if normalized == "direct_reports":
            return tuple(sorted(name for name, agent in self.agents.items() if agent.manager == sender))
        if normalized == "manager":
            manager = self.agents[sender].manager
            return (manager,) if manager else ()
        if normalized == "peers":
            manager = self.agents[sender].manager
            if not manager:
                return ()
            return tuple(sorted(name for name, agent in self.agents.items() if name != sender and agent.manager == manager))
        if normalized == "team":
            team = self.agents[sender].team
            if not team:
                return ()
            return tuple(sorted(name for name, agent in self.agents.items() if name != sender and agent.team == team))
        if normalized in self.groups:
            return self.groups[normalized].agents
        return (self.resolve_agent(target),)

    def can_route(self, sender: str, recipient: str) -> bool:
        if self.routing.mode == "flat":
            return True
        if sender == recipient:
            return True
        return (
            _is_manager_chain_related(self.agents, sender, recipient)
            or _is_manager_chain_related(self.agents, recipient, sender)
            or _same_manager(self.agents, sender, recipient)
        )


def load_org(path: Path) -> OrgConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("org config must be a mapping")

    agents = _load_agents(raw.get("agents"))
    topics = _load_topics(raw.get("topics"), agents)
    groups = _load_groups(raw.get("groups"), agents)
    routing = _load_routing(raw.get("routing"), agents)
    skill = raw.get("skill", "skills/agent-comms/SKILL.md")
    max_messages = int(raw.get("max_messages", 10))
    if max_messages < 1:
        raise ValueError("max_messages must be at least 1")
    scatter_timeout = int(raw.get("scatter_timeout", 120))
    if scatter_timeout < 1:
        raise ValueError("scatter_timeout must be at least 1")

    return OrgConfig(
        agents=agents,
        topics=topics,
        groups=groups,
        routing=routing,
        skill_path=(path.parent.parent / str(skill)).resolve(),
        max_messages=max_messages,
        scatter_timeout=scatter_timeout,
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
        title = _optional_string(value, "title", name)
        team = _optional_string(value, "team", "")
        manager = _optional_string(value, "manager", "")
        agents[name] = AgentConfig(
            name=name,
            command=command,
            expertise=expertise.strip(),
            title=title.strip(),
            team=team.strip(),
            manager=manager.strip(),
        )
    unknown_managers = sorted({agent.manager for agent in agents.values() if agent.manager} - set(agents))
    if unknown_managers:
        raise ValueError(f"agent manager references unknown agent(s): {', '.join(unknown_managers)}")
    _reject_manager_cycles(agents)
    return agents


def _optional_string(value: dict[str, Any], key: str, default: str) -> str:
    raw = value.get(key, default)
    if not isinstance(raw, str):
        raise ValueError(f"agent {key} must be a string")
    return raw


def _load_topics(raw: Any, agents: dict[str, AgentConfig]) -> dict[str, TopicConfig]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("topics must be a mapping")

    topics: dict[str, TopicConfig] = {}
    for name, value in raw.items():
        if not isinstance(name, str):
            raise ValueError("topic ids must be strings")
        if not isinstance(value, dict):
            raise ValueError(f"topic {name} must be a mapping")
        default = value.get("default")
        members = value.get("agents", [])
        if not isinstance(default, str) or not default:
            raise ValueError(f"topic {name} must define default")
        if not isinstance(members, list) or not all(isinstance(member, str) for member in members):
            raise ValueError(f"topic {name} agents must be a list of strings")
        unknown = sorted({default, *members} - set(agents))
        if unknown:
            raise ValueError(f"topic {name} references unknown agent(s): {', '.join(unknown)}")
        topics[name] = TopicConfig(name=name, default=default, agents=tuple(members))
    return topics


def _load_groups(raw: Any, agents: dict[str, AgentConfig]) -> dict[str, GroupConfig]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("groups must be a mapping")

    groups: dict[str, GroupConfig] = {}
    for name, value in raw.items():
        if not isinstance(name, str):
            raise ValueError("group ids must be strings")
        if not isinstance(value, list) or not all(isinstance(member, str) for member in value):
            raise ValueError(f"group {name} must be a list of agent ids")
        if not value:
            raise ValueError(f"group {name} must include at least one agent")
        if name in BUILT_IN_BROADCASTS:
            raise ValueError(f"group {name} conflicts with built-in broadcast target @{name}")
        unknown = sorted(set(value) - set(agents))
        if unknown:
            raise ValueError(f"group {name} references unknown agent(s): {', '.join(unknown)}")
        groups[name] = GroupConfig(name=name, agents=tuple(value))
    return groups


def _load_routing(raw: Any, agents: dict[str, AgentConfig]) -> RoutingPolicy:
    if raw is None:
        return RoutingPolicy(mode="flat")
    if not isinstance(raw, str) or raw not in {"flat", "strict_hierarchical"}:
        raise ValueError("routing must be flat or strict_hierarchical")
    return RoutingPolicy(mode=raw)


def _is_manager_chain_related(agents: dict[str, AgentConfig], manager: str, report: str) -> bool:
    current = agents[report].manager
    while current:
        if current == manager:
            return True
        current = agents[current].manager
    return False


def _same_manager(agents: dict[str, AgentConfig], sender: str, recipient: str) -> bool:
    sender_manager = agents[sender].manager
    return bool(sender_manager and sender_manager == agents[recipient].manager)


def _reject_manager_cycles(agents: dict[str, AgentConfig]) -> None:
    for name in agents:
        seen: set[str] = set()
        current = agents[name].manager
        while current:
            if current in seen or current == name:
                raise ValueError(f"agent manager hierarchy contains a cycle involving {name}")
            seen.add(current)
            current = agents[current].manager
