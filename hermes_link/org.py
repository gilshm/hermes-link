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
    title: str = ""
    team: str = ""
    manager: str = ""


@dataclass(frozen=True)
class TopicConfig:
    name: str
    default: str
    agents: tuple[str, ...]


@dataclass(frozen=True)
class RoutingPolicy:
    default: str
    allow: dict[str, tuple[str, ...]]
    deny: dict[str, tuple[str, ...]]

    def is_allowed(self, sender: str, recipient: str) -> bool:
        if _matches_policy(self.deny, sender, recipient):
            return False
        if _matches_policy(self.allow, sender, recipient):
            return True
        return self.default == "allow"


@dataclass(frozen=True)
class OrgConfig:
    agents: dict[str, AgentConfig]
    topics: dict[str, TopicConfig]
    routing: RoutingPolicy
    skill_path: Path
    max_messages: int

    def resolve_agent(self, target: str) -> str:
        normalized = target.removeprefix("@")
        if normalized in self.agents:
            return normalized
        if normalized in self.topics:
            return self.topics[normalized].default
        raise ValueError(f"unknown agent or topic: {target}")

    def can_route(self, sender: str, recipient: str) -> bool:
        return self.routing.is_allowed(sender, recipient)


def load_org(path: Path) -> OrgConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("org config must be a mapping")

    agents = _load_agents(raw.get("agents"))
    topics = _load_topics(raw.get("topics"), agents)
    routing = _load_routing(raw.get("routing"), agents)
    skill = raw.get("skill", "skills/agent-comms/SKILL.md")
    max_messages = int(raw.get("max_messages", 10))
    if max_messages < 1:
        raise ValueError("max_messages must be at least 1")

    return OrgConfig(
        agents=agents,
        topics=topics,
        routing=routing,
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


def _load_routing(raw: Any, agents: dict[str, AgentConfig]) -> RoutingPolicy:
    if raw is None:
        return RoutingPolicy(default="allow", allow={}, deny={})
    if not isinstance(raw, dict):
        raise ValueError("routing must be a mapping")
    default = raw.get("default", "allow")
    if default not in {"allow", "deny"}:
        raise ValueError("routing default must be allow or deny")
    allow = _load_policy_map(raw.get("allow", {}), agents, key="allow")
    deny = _load_policy_map(raw.get("deny", {}), agents, key="deny")
    return RoutingPolicy(default=default, allow=allow, deny=deny)


def _load_policy_map(raw: Any, agents: dict[str, AgentConfig], *, key: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise ValueError(f"routing {key} must be a mapping")

    policy: dict[str, tuple[str, ...]] = {}
    for sender, recipients in raw.items():
        if sender != "*" and sender not in agents:
            raise ValueError(f"routing {key} references unknown sender: {sender}")
        if not isinstance(recipients, list) or not all(isinstance(recipient, str) for recipient in recipients):
            raise ValueError(f"routing {key} for {sender} must be a list of agent ids")
        unknown = sorted(recipient for recipient in recipients if recipient != "*" and recipient not in agents)
        if unknown:
            raise ValueError(f"routing {key} for {sender} references unknown recipient(s): {', '.join(unknown)}")
        policy[sender] = tuple(recipients)
    return policy


def _matches_policy(policy: dict[str, tuple[str, ...]], sender: str, recipient: str) -> bool:
    for source in (sender, "*"):
        recipients = policy.get(source, ())
        if "*" in recipients or recipient in recipients:
            return True
    return False
