from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from hermes_link.doctor import run_doctor
from hermes_link.hermes_runner import HermesRunner
from hermes_link.log import EventLog, default_log_path, format_event, format_trace, format_trace_mermaid, iter_events, trace_events
from hermes_link.org import OrgConfig, load_org
from hermes_link.session_map import SessionMap
from hermes_link.status import check_agent_health, inspect_agent, yes_no
from hermes_link.validation import validate_org


REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes_link")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat = subparsers.add_parser("chat", help="Talk to an org agent with Hermes Link routing")
    chat.add_argument("agent")
    chat.add_argument("prompt")
    chat.add_argument("--org", type=Path, default=REPO_ROOT / "config" / "org.yaml")
    chat.add_argument("--max-messages", type=int, default=None)
    chat.add_argument("--timeout", type=int, default=120)
    chat.add_argument("--thread-id", default=None, help="Trace id to use for this routed conversation")
    chat.add_argument("--log-path", type=Path, default=default_log_path(REPO_ROOT))

    log = subparsers.add_parser("log", help="Show Hermes Link message log")
    log.add_argument("--path", type=Path, default=default_log_path(REPO_ROOT))
    log.add_argument("--watch", "-w", action="store_true")
    log.add_argument("--interval", type=float, default=1.0)
    log.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    log.add_argument("--max-body-chars", type=int, default=None, help="Only show the first N characters of message bodies")

    trace = subparsers.add_parser("trace", help="Show one routed conversation trace")
    trace.add_argument("thread_id")
    trace.add_argument("--path", type=Path, default=default_log_path(REPO_ROOT))
    trace.add_argument("--format", choices=["text", "mermaid"], default="text")
    trace.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    trace.add_argument("--max-body-chars", type=int, default=None, help="Only show the first N characters of message bodies")

    agents = subparsers.add_parser("agents", help="Show configured org agents")
    agents.add_argument("--org", type=Path, default=REPO_ROOT / "config" / "org.yaml")
    agents.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes")
    agents.add_argument("--check", action="store_true", help="Run a smoke prompt against each agent")
    agents.add_argument("--timeout", type=int, default=30)

    sessions = subparsers.add_parser("sessions", help="Show Hermes Link session mappings")
    sessions.add_argument("--path", type=Path, default=REPO_ROOT / ".hermes-link" / "session-map.json")
    sessions.add_argument("--thread", help="Show sessions observed in one logged thread")
    sessions.add_argument("--log-path", type=Path, default=default_log_path(REPO_ROOT))

    cleanup = subparsers.add_parser("cleanup", help="Clean Hermes Link state files")
    cleanup.add_argument("--state-dir", type=Path, default=REPO_ROOT / ".hermes-link")
    cleanup.add_argument("--log-path", type=Path, default=default_log_path(REPO_ROOT))
    cleanup.add_argument("--lock-older-than-seconds", type=float, default=24 * 60 * 60)
    cleanup.add_argument("--max-log-bytes", type=int, default=None)

    doctor = subparsers.add_parser("doctor", help="Check Hermes Link config and install state")
    doctor.add_argument("--org", type=Path, default=REPO_ROOT / "config" / "org.yaml")
    doctor.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes")
    doctor.add_argument("--check-agents", action="store_true", help="Run live smoke prompts for configured agents")
    doctor.add_argument("--route-matrix", action="store_true", help="Show static allowed/blocked routes from org policy")
    doctor.add_argument("--live-route-matrix", action="store_true", help="Ask real agents to emit SEND directives and verify route policy behavior")
    doctor.add_argument("--route-from", help="Limit route matrix checks to one sender agent")
    doctor.add_argument("--route-to", help="Limit route matrix checks to one recipient agent")
    doctor.add_argument("--timeout", type=int, default=30)

    org_parser = subparsers.add_parser("org", help="Org configuration commands")
    org_subparsers = org_parser.add_subparsers(dest="org_command", required=True)
    org_validate = org_subparsers.add_parser("validate", help="Validate config/org.yaml")
    org_validate.add_argument("--org", type=Path, default=REPO_ROOT / "config" / "org.yaml")
    org_graph = org_subparsers.add_parser("graph", help="Print the configured org hierarchy")
    org_graph.add_argument("--org", type=Path, default=REPO_ROOT / "config" / "org.yaml")

    args = parser.parse_args(argv)
    if args.command == "chat":
        thread_id = args.thread_id or f"cli-{uuid4().hex[:8]}"
        result = HermesRunner(
            load_org(args.org),
            cwd=REPO_ROOT,
            timeout=args.timeout,
            event_log=EventLog(args.log_path),
            thread_id=thread_id,
        ).chat(args.agent, args.prompt, max_messages=args.max_messages)
        print(f"thread_id: {thread_id}")
        for message in result.transcript[1:]:
            print(f"{message.sender} -> {message.recipient}: {message.body}")
        if len(result.transcript) > 1 and result.turns:
            if result.handoff or result.turns[-1].agent == result.transcript[0].recipient:
                print(result.final_response)
            else:
                previous = result.transcript[-1]
                print(f"{result.turns[-1].agent} -> {previous.sender}: {result.final_response}")
        else:
            print(result.final_response)
        return 0
    if args.command == "log":
        color = _use_color(args.color)
        max_body_chars = _validate_max_body_chars(args.max_body_chars)
        if args.watch:
            return _watch_log(args.path, interval=args.interval, color=color, max_body_chars=max_body_chars)
        for event in iter_events(args.path):
            print(format_event(event, color=color, max_body_chars=max_body_chars))
        return 0
    if args.command == "trace":
        color = _use_color(args.color)
        max_body_chars = _validate_max_body_chars(args.max_body_chars)
        events = trace_events(args.path, args.thread_id)
        if args.format == "mermaid":
            print(format_trace_mermaid(events, thread_id=args.thread_id))
        else:
            print(format_trace(events, thread_id=args.thread_id, color=color, max_body_chars=max_body_chars))
        return 0
    if args.command == "agents":
        org = load_org(args.org)
        for name in sorted(org.agents):
            status = inspect_agent(org.agents[name], hermes_home=args.hermes_home)
            print(f"{name}")
            print(f"  command: {status.agent.command} ({'found' if status.command_available else 'missing'})")
            print(f"  expertise: {status.agent.expertise or 'not specified'}")
            if status.agent.capabilities:
                print(f"  capabilities: {', '.join(status.agent.capabilities)}")
            print(f"  skill installed: {yes_no(status.skill_installed)}")
            print(f"  plugin installed: {yes_no(status.plugin_installed)}")
            print(f"  plugin enabled: {yes_no(status.plugin_enabled)}")
            if args.check:
                health = check_agent_health(org.agents[name], timeout=args.timeout, cwd=REPO_ROOT)
                state = "ok" if health.ok else "failed"
                detail = health.response if health.ok else health.error
                print(f"  health: {state} ({health.elapsed_seconds:.2f}s)")
                if detail:
                    print(f"  health detail: {detail}")
        return 0
    if args.command == "doctor":
        checks = run_doctor(
            org_path=args.org,
            repo_root=REPO_ROOT,
            hermes_home=args.hermes_home,
            check_agents=args.check_agents,
            route_matrix=args.route_matrix,
            live_route_matrix=args.live_route_matrix,
            route_from=args.route_from,
            route_to=args.route_to,
            timeout=args.timeout,
        )
        for check in checks:
            print(f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}")
        return 0 if all(check.ok for check in checks) else 1
    if args.command == "sessions":
        if args.thread:
            print(_format_thread_sessions(trace_events(args.log_path, args.thread), thread_id=args.thread))
            return 0
        entries = SessionMap(args.path).entries()
        if not entries:
            print("No session mappings.")
            return 0
        for source_session_id, agent, target_session_id in entries:
            print(f"{source_session_id} -> {agent}: {target_session_id}")
        return 0
    if args.command == "cleanup":
        removed_locks = _cleanup_locks(args.state_dir / "locks", older_than_seconds=args.lock_older_than_seconds)
        rotated_log = _rotate_log_if_needed(args.log_path, max_bytes=args.max_log_bytes)
        print(f"removed locks: {removed_locks}")
        if rotated_log is not None:
            print(f"rotated log: {rotated_log}")
        return 0
    if args.command == "org" and args.org_command == "validate":
        errors = validate_org(args.org, repo_root=REPO_ROOT)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("org config ok")
        return 0
    if args.command == "org" and args.org_command == "graph":
        print(_format_org_graph(load_org(args.org)))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def _format_thread_sessions(events: list[dict], *, thread_id: str) -> str:
    sessions: set[tuple[str, str]] = set()
    for event in events:
        if event.get("from_agent") and event.get("from_session_id"):
            sessions.add((str(event["from_agent"]), str(event["from_session_id"])))
        if event.get("to_agent") and event.get("to_session_id"):
            sessions.add((str(event["to_agent"]), str(event["to_session_id"])))
        if event.get("agent") and event.get("session_id"):
            sessions.add((str(event["agent"]), str(event["session_id"])))
    if not sessions:
        return f"No sessions found for thread: {thread_id}"
    lines = [f"Sessions for thread {thread_id}"]
    for agent, session_id in sorted(sessions):
        lines.append(f"{agent}: {session_id}")
    return "\n".join(lines)


def _cleanup_locks(path: Path, *, older_than_seconds: float) -> int:
    if not path.exists():
        return 0
    threshold = time.time() - older_than_seconds
    removed = 0
    for lock in path.glob("*.lock"):
        if lock.stat().st_mtime <= threshold:
            lock.unlink()
            removed += 1
    return removed


def _rotate_log_if_needed(path: Path, *, max_bytes: int | None) -> Path | None:
    if max_bytes is None or max_bytes < 1 or not path.exists() or path.stat().st_size <= max_bytes:
        return None
    rotated = path.with_name(f"{path.name}.1")
    if rotated.exists():
        rotated.unlink()
    path.rename(rotated)
    return rotated


def _format_org_graph(org: OrgConfig) -> str:
    agents = org.agents
    children: dict[str, list[str]] = {name: [] for name in agents}
    roots = []
    for name, agent in agents.items():
        if agent.manager:
            children[agent.manager].append(name)
        else:
            roots.append(name)
    for names in children.values():
        names.sort()
    roots.sort()

    lines = [f"routing: {org.routing.mode}", "agents:"]
    for index, root in enumerate(roots):
        _append_agent_tree(lines, agents, children, root, prefix="", is_last=index == len(roots) - 1)
    if org.groups:
        lines.append("groups:")
        for name in sorted(org.groups):
            lines.append(f"- @{name}: {', '.join(org.groups[name].agents)}")
    lines.extend(
        [
            "built-ins:",
            "- @direct_reports: sender's direct reports",
            "- @manager: sender's manager",
            "- @peers: sender's same-manager peers",
            "- @team: sender's same-team peers",
        ]
    )
    return "\n".join(lines)


def _append_agent_tree(
    lines: list[str],
    agents: dict,
    children: dict[str, list[str]],
    name: str,
    *,
    prefix: str,
    is_last: bool,
) -> None:
    connector = "`-- " if is_last else "|-- "
    agent = agents[name]
    title = agent.title or name
    details = []
    if agent.team:
        details.append(f"team={agent.team}")
    if agent.manager:
        details.append(f"manager={agent.manager}")
    if agent.capabilities:
        details.append(f"capabilities={','.join(agent.capabilities)}")
    suffix = f" ({'; '.join(details)})" if details else ""
    lines.append(f"{prefix}{connector}{name}: {title}{suffix}")
    next_prefix = prefix + ("    " if is_last else "|   ")
    child_names = children[name]
    for index, child in enumerate(child_names):
        _append_agent_tree(
            lines,
            agents,
            children,
            child,
            prefix=next_prefix,
            is_last=index == len(child_names) - 1,
        )


def _watch_log(path: Path, *, interval: float, color: bool, max_body_chars: int | None = None) -> int:
    seen = 0
    while True:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines[seen:]:
                if line.strip():
                    print(format_event(json.loads(line), color=color, max_body_chars=max_body_chars), flush=True)
            seen = len(lines)
        time.sleep(interval)


def _use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return __import__("sys").stdout.isatty()


def _validate_max_body_chars(value: int | None) -> int | None:
    if value is not None and value < 0:
        raise ValueError("--max-body-chars must be 0 or greater")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
