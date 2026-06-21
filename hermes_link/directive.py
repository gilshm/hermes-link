from __future__ import annotations

import re
from dataclasses import dataclass


_SEND_RE = re.compile(r"^\s*SEND\s+([A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$", re.DOTALL)


@dataclass(frozen=True)
class SendDirective:
    recipient: str
    body: str


def parse_send_directive(text: str) -> SendDirective | None:
    match = _SEND_RE.match(text.strip())
    if match is None:
        return None
    return SendDirective(recipient=match.group(1), body=match.group(2).strip())
