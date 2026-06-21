from __future__ import annotations

from hermes_link.agent import Agent
from hermes_link.message import Message
from hermes_link.runtime import Runtime


def build_demo_runtime() -> Runtime:
    runtime = Runtime()

    def agent_a(message: Message) -> None:
        return None

    def agent_b(message: Message) -> Message:
        return Message(sender="agent_b", recipient=message.sender, body="pong")

    runtime.register(Agent("agent_a", agent_a))
    runtime.register(Agent("agent_b", agent_b))
    return runtime


def run_demo() -> list[Message]:
    runtime = build_demo_runtime()
    return runtime.send(Message(sender="agent_a", recipient="agent_b", body="ping"))


def main() -> int:
    for message in run_demo():
        print(f"{message.sender} -> {message.recipient}: {message.body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
