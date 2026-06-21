from __future__ import annotations

from hermes_link.agent import Agent
from hermes_link.message import Message


class Runtime:
    """Synchronous in-memory message delivery."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if agent.name in self._agents:
            raise ValueError(f"agent already registered: {agent.name}")
        self._agents[agent.name] = agent

    def send(self, message: Message, *, max_hops: int = 10) -> list[Message]:
        if max_hops < 1:
            raise ValueError("max_hops must be at least 1")

        transcript: list[Message] = []
        current: Message | None = message

        for _ in range(max_hops):
            if current is None:
                return transcript

            self._ensure_known_agent(current.sender)
            recipient = self._ensure_known_agent(current.recipient)
            transcript.append(current)
            current = recipient.handle(current)

        if current is not None:
            raise RuntimeError("message exchange exceeded max_hops")

        return transcript

    def _ensure_known_agent(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise ValueError(f"unknown agent: {name}") from exc
