from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from hermes_link.hermes_runner import HermesRunner
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
    route_matrix: bool = False,
    live_route_matrix: bool = False,
    route_from: str | None = None,
    route_to: str | None = None,
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

    if route_matrix:
        checks.extend(_route_matrix_checks(org, route_from=route_from, route_to=route_to))
    if live_route_matrix:
        checks.extend(_live_route_matrix_checks(org, repo_root=repo_root, timeout=timeout, route_from=route_from, route_to=route_to))

    return checks


def _check_writable_state_dir(path: Path) -> DoctorCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".doctor-", delete=True):
            pass
    except OSError as exc:
        return DoctorCheck(name="state dir", ok=False, detail=str(exc))
    return DoctorCheck(name="state dir", ok=True, detail=str(path))


def _route_matrix_checks(org, *, route_from: str | None, route_to: str | None) -> list[DoctorCheck]:
    checks = []
    for sender, recipient in _route_pairs(org, route_from=route_from, route_to=route_to):
        allowed = org.can_route(sender, recipient)
        checks.append(
            DoctorCheck(
                name=f"route {sender} -> {recipient}",
                ok=True,
                detail="allowed" if allowed else "blocked by policy",
            )
        )
    return checks


def _live_route_matrix_checks(org, *, repo_root: Path, timeout: int, route_from: str | None, route_to: str | None) -> list[DoctorCheck]:
    checks = []
    for sender, recipient in _route_pairs(org, route_from=route_from, route_to=route_to):
        expected_allowed = org.can_route(sender, recipient)
        prompt = (
            "Output exactly one Hermes Link SEND directive and no extra text:\n"
            f"SEND {recipient}: HERMES_LINK_DOCTOR_ROUTE {sender} to {recipient}"
        )
        try:
            routed = HermesRunner(org, cwd=repo_root, timeout=timeout).request_send(sender, prompt)
        except Exception as exc:
            detail = str(exc)
            if expected_allowed:
                checks.append(DoctorCheck(name=f"live route {sender} -> {recipient}", ok=False, detail=detail))
            else:
                checks.append(
                    DoctorCheck(
                        name=f"live route {sender} -> {recipient}",
                        ok="routing policy blocked" in detail,
                        detail="blocked by policy" if "routing policy blocked" in detail else detail,
                    )
                )
            continue

        if expected_allowed:
            checks.append(
                DoctorCheck(
                    name=f"live route {sender} -> {recipient}",
                    ok=routed.message.recipient == recipient,
                    detail=f"allowed: {routed.message.sender} -> {routed.message.recipient}",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    name=f"live route {sender} -> {recipient}",
                    ok=False,
                    detail=f"expected policy block, but routed to {routed.message.recipient}",
                )
            )
    return checks


def _route_pairs(org, *, route_from: str | None, route_to: str | None) -> list[tuple[str, str]]:
    agents = sorted(org.agents)
    if route_from is not None and route_from not in org.agents:
        raise ValueError(f"unknown route sender: {route_from}")
    if route_to is not None and route_to not in org.agents:
        raise ValueError(f"unknown route recipient: {route_to}")
    senders = [route_from] if route_from else agents
    recipients = [route_to] if route_to else agents
    return [(sender, recipient) for sender in senders for recipient in recipients if sender != recipient]
