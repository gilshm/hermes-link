from __future__ import annotations

import argparse
from pathlib import Path

from hermes_link.hermes_runner import HermesRunner
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

    args = parser.parse_args(argv)
    if args.command == "chat":
        result = HermesRunner(
            load_org(args.org),
            cwd=REPO_ROOT,
            timeout=args.timeout,
        ).chat(args.agent, args.prompt, max_messages=args.max_messages)
        for message in result.transcript[1:]:
            print(f"{message.sender} -> {message.recipient}: {message.body}")
        print(result.final_response)
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
