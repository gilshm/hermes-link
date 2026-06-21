from __future__ import annotations

import json
from pathlib import Path


class SessionMap:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, *, source_session_id: str, agent: str) -> str | None:
        return self._load().get(self._key(source_session_id, agent))

    def set(self, *, source_session_id: str, agent: str, target_session_id: str) -> None:
        data = self._load()
        data[self._key(source_session_id, agent)] = target_session_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"session map must contain a JSON object: {self.path}")
        return {str(key): str(value) for key, value in raw.items()}

    def _key(self, source_session_id: str, agent: str) -> str:
        return f"{source_session_id}:{agent}"
