from __future__ import annotations

from hermes_link.agent import Agent
from hermes_link.message import Message
from hermes_link.runtime import Runtime


def build_demo_runtime() -> Runtime:
    runtime = Runtime()

    def hl_ceo(message: Message) -> None:
        return None

    def hl_advisor(message: Message) -> Message:
        return Message(sender="hl_advisor", recipient=message.sender, body="pong")

    runtime.register(Agent("hl_ceo", hl_ceo))
    runtime.register(Agent("hl_advisor", hl_advisor))
    return runtime


def run_demo() -> list[Message]:
    runtime = build_demo_runtime()
    return runtime.send(Message(sender="hl_ceo", recipient="hl_advisor", body="ping"))


def main() -> int:
    for message in run_demo():
        print(f"{message.sender} -> {message.recipient}: {message.body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
