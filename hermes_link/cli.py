from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from hermes_link.hermes_runner import HermesRunner
from hermes_link.log import EventLog, default_log_path, format_event, iter_events
from hermes_link.org import load_org


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

    args = parser.parse_args(argv)
    if args.command == "chat":
        result = HermesRunner(
            load_org(args.org),
            cwd=REPO_ROOT,
            timeout=args.timeout,
            event_log=EventLog(default_log_path(REPO_ROOT)),
        ).chat(args.agent, args.prompt, max_messages=args.max_messages)
        for message in result.transcript[1:]:
            print(f"{message.sender} -> {message.recipient}: {message.body}")
        print(result.final_response)
        return 0
    if args.command == "log":
        if args.watch:
            return _watch_log(args.path, interval=args.interval)
        for event in iter_events(args.path):
            print(format_event(event))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def _watch_log(path: Path, *, interval: float) -> int:
    seen = 0
    while True:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines[seen:]:
                if line.strip():
                    print(format_event(json.loads(line)), flush=True)
            seen = len(lines)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
