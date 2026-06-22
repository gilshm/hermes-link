from __future__ import annotations

import re
from dataclasses import dataclass


_SEND_RE = re.compile(r"^\s*SEND\s+(@?[A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$", re.DOTALL)
_SEND_ALL_HEADER_RE = re.compile(r"^\s*SEND_ALL\s*:\s*$")
_SEND_ALL_ITEM_RE = re.compile(r"^\s*-\s+(@?[A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$", re.DOTALL)


@dataclass(frozen=True)
class SendDirective:
    recipient: str
    body: str


@dataclass(frozen=True)
class SendAllDirective:
    sends: tuple[SendDirective, ...]


def parse_send_directive(text: str) -> SendDirective | SendAllDirective | None:
    send_all = _parse_send_all_directive(text)
    if send_all is not None:
        return send_all
    match = _SEND_RE.match(text.strip())
    if match is None:
        return None
    return SendDirective(recipient=match.group(1), body=match.group(2).strip())


def _parse_send_all_directive(text: str) -> SendAllDirective | None:
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    if not lines or _SEND_ALL_HEADER_RE.match(lines[0]) is None:
        return None
    sends = []
    for line in lines[1:]:
        match = _SEND_ALL_ITEM_RE.match(line)
        if match is None:
            return None
        sends.append(SendDirective(recipient=match.group(1), body=match.group(2).strip()))
    if not sends:
        return None
    return SendAllDirective(sends=tuple(sends))
