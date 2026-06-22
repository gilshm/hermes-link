from __future__ import annotations

import shutil
from pathlib import Path

from hermes_link.org import OrgConfig, load_org


def validate_org(path: Path, *, repo_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        org = load_org(path)
    except Exception as exc:
        return [str(exc)]

    errors.extend(_validate_agents(org))
    if not org.skill_path.exists():
        errors.append(f"skill file does not exist: {org.skill_path}")
    plugin = repo_root / ".hermes" / "plugins" / "hermes-link" / "plugin.yaml"
    if not plugin.exists():
        errors.append(f"plugin source does not exist: {plugin}")
    return errors


def _validate_agents(org: OrgConfig) -> list[str]:
    errors: list[str] = []
    for name, agent in sorted(org.agents.items()):
        if not agent.expertise:
            errors.append(f"agent {name} is missing expertise")
        if shutil.which(agent.command) is None:
            errors.append(f"agent {name} command not found: {agent.command}")
    for name, topic in sorted(org.topics.items()):
        if topic.default not in org.agents:
            errors.append(f"topic {name} default is unknown: {topic.default}")
        for agent in topic.agents:
            if agent not in org.agents:
                errors.append(f"topic {name} references unknown agent: {agent}")
    for name, group in sorted(org.groups.items()):
        if not group.agents:
            errors.append(f"group {name} has no agents")
        for agent in group.agents:
            if agent not in org.agents:
                errors.append(f"group {name} references unknown agent: {agent}")
    return errors
