from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from hermes_link.org import load_org
from hermes_link.status import check_agent_health, inspect_agent, yes_no
from hermes_link.validation import validate_org


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def run_doctor(
    *,
    org_path: Path,
    repo_root: Path,
    hermes_home: Path,
    check_agents: bool = False,
    timeout: int = 30,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    org_errors = validate_org(org_path, repo_root=repo_root)
    checks.append(
        DoctorCheck(
            name="org config",
            ok=not org_errors,
            detail="ok" if not org_errors else "; ".join(org_errors),
        )
    )

    try:
        org = load_org(org_path)
    except Exception:
        org = None

    state_dir = repo_root / ".hermes-link"
    checks.append(_check_writable_state_dir(state_dir))

    if org is None:
        return checks

    for name in sorted(org.agents):
        status = inspect_agent(org.agents[name], hermes_home=hermes_home)
        checks.append(
            DoctorCheck(
                name=f"agent {name}",
                ok=status.command_available and status.skill_installed and status.plugin_installed and status.plugin_enabled is True,
                detail=(
                    f"command={yes_no(status.command_available)}, "
                    f"skill={yes_no(status.skill_installed)}, "
                    f"plugin={yes_no(status.plugin_installed)}, "
                    f"enabled={yes_no(status.plugin_enabled)}"
                ),
            )
        )
        if check_agents:
            health = check_agent_health(org.agents[name], timeout=timeout, cwd=repo_root)
            checks.append(
                DoctorCheck(
                    name=f"agent {name} health",
                    ok=health.ok,
                    detail=health.response if health.ok else health.error,
                )
            )

    return checks


def _check_writable_state_dir(path: Path) -> DoctorCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".doctor-", delete=True):
            pass
    except OSError as exc:
        return DoctorCheck(name="state dir", ok=False, detail=str(exc))
    return DoctorCheck(name="state dir", ok=True, detail=str(path))
