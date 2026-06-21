from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    sender: str
    recipient: str
    body: str
