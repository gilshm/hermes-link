from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hermes_link.message import Message


MessageHandler = Callable[[Message], Message | None]


@dataclass(frozen=True)
class Agent:
    """A named message handler."""

    name: str
    handler: MessageHandler

    def handle(self, message: Message) -> Message | None:
        return self.handler(message)
