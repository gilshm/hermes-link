from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from hermes_link.hermes_runner import HermesRunner
from hermes_link.log import EventLog, default_log_path, format_event, format_trace, iter_events, trace_events
from hermes_link.org import load_org
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

    log = subparsers.add_parser("log", help="Show Hermes Link message log")
    log.add_argument("--path", type=Path, default=default_log_path(REPO_ROOT))
    log.add_argument("--watch", "-w", action="store_true")
    log.add_argument("--interval", type=float, default=1.0)
    log.add_argument("--color", choices=["auto", "always", "never"], default="auto")

    trace = subparsers.add_parser("trace", help="Show one routed conversation trace")
    trace.add_argument("thread_id")
    trace.add_argument("--path", type=Path, default=default_log_path(REPO_ROOT))
    trace.add_argument("--color", choices=["auto", "always", "never"], default="auto")

    agents = subparsers.add_parser("agents", help="Show configured org agents")
    agents.add_argument("--org", type=Path, default=REPO_ROOT / "config" / "org.yaml")
    agents.add_argument("--hermes-home", type=Path, default=Path.home() / ".hermes")
    agents.add_argument("--check", action="store_true", help="Run a smoke prompt against each agent")
    agents.add_argument("--timeout", type=int, default=30)

    sessions = subparsers.add_parser("sessions", help="Show Hermes Link session mappings")
    sessions.add_argument("--path", type=Path, default=REPO_ROOT / ".hermes-link" / "session-map.json")

    org_parser = subparsers.add_parser("org", help="Org configuration commands")
    org_subparsers = org_parser.add_subparsers(dest="org_command", required=True)
    org_validate = org_subparsers.add_parser("validate", help="Validate config/org.yaml")
    org_validate.add_argument("--org", type=Path, default=REPO_ROOT / "config" / "org.yaml")

    args = parser.parse_args(argv)
    if args.command == "chat":
        result = HermesRunner(
            load_org(args.org),
            cwd=REPO_ROOT,
            timeout=args.timeout,
            event_log=EventLog(default_log_path(REPO_ROOT)),
            thread_id=f"cli-{uuid4().hex[:8]}",
        ).chat(args.agent, args.prompt, max_messages=args.max_messages)
        for message in result.transcript[1:]:
            print(f"{message.sender} -> {message.recipient}: {message.body}")
        if len(result.transcript) > 1 and result.turns:
            if result.turns[-1].agent == result.transcript[0].recipient:
                print(result.final_response)
            else:
                previous = result.transcript[-1]
                print(f"{result.turns[-1].agent} -> {previous.sender}: {result.final_response}")
        else:
            print(result.final_response)
        return 0
    if args.command == "log":
        color = _use_color(args.color)
        if args.watch:
            return _watch_log(args.path, interval=args.interval, color=color)
        for event in iter_events(args.path):
            print(format_event(event, color=color))
        return 0
    if args.command == "trace":
        color = _use_color(args.color)
        print(format_trace(trace_events(args.path, args.thread_id), thread_id=args.thread_id, color=color))
        return 0
    if args.command == "agents":
        org = load_org(args.org)
        for name in sorted(org.agents):
            status = inspect_agent(org.agents[name], hermes_home=args.hermes_home)
            print(f"{name}")
            print(f"  command: {status.agent.command} ({'found' if status.command_available else 'missing'})")
            print(f"  expertise: {status.agent.expertise or 'not specified'}")
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
    if args.command == "sessions":
        entries = SessionMap(args.path).entries()
        if not entries:
            print("No session mappings.")
            return 0
        for source_session_id, agent, target_session_id in entries:
            print(f"{source_session_id} -> {agent}: {target_session_id}")
        return 0
    if args.command == "org" and args.org_command == "validate":
        errors = validate_org(args.org, repo_root=REPO_ROOT)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("org config ok")
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def _watch_log(path: Path, *, interval: float, color: bool) -> int:
    seen = 0
    while True:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines[seen:]:
                if line.strip():
                    print(format_event(json.loads(line), color=color), flush=True)
            seen = len(lines)
        time.sleep(interval)


def _use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return __import__("sys").stdout.isatty()


if __name__ == "__main__":
    raise SystemExit(main())
