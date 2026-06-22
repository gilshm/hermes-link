import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link import bridge_runner


class BridgeRunnerTests(unittest.TestCase):
    def test_bridge_reuses_target_session_for_source_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_repo_shape(root)
            calls: list[list[str]] = []
            outputs = [
                "session_id: session-b\nfirst",
                "session_id: session-b\nsecond",
            ]

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout=outputs.pop(0), stderr="")

            payload = {
                "from_agent": "hl_ceo",
                "to": "hl_advisor",
                "body": "hello",
                "source_session_id": "session-a",
            }
            with (
                mock.patch("sys.stdin.read", return_value=json.dumps(payload)),
                mock.patch.dict(os.environ, {"HERMES_LINK_HOME": str(root), "HERMES_LINK_STATE_DIR": str(root / "state")}),
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch.object(sys, "stdout", new_callable=_Capture) as output,
            ):
                bridge_runner.main()
                bridge_runner.main()

            self.assertNotIn("-r", calls[0])
            self.assertIn("-r", calls[1])
            self.assertEqual(calls[1][calls[1].index("-r") + 1], "session-b")
            events = (root / "state" / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "bridge_request"', events)
            self.assertIn('"event": "final"', events)
            self.assertIn('"thread_id": "session-a"', events)
            self.assertIn("Hermes Link transcript:", output.value)
            self.assertIn("Final from hl_advisor:", output.value)

    def test_bridge_reports_policy_block_to_sender(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_repo_shape(root, policy_block=True)
            payload = {
                "from_agent": "hl_ceo",
                "to": "hl_advisor",
                "body": "hello",
                "source_session_id": "session-a",
            }
            with (
                mock.patch("sys.stdin.read", return_value=json.dumps(payload)),
                mock.patch.dict(os.environ, {"HERMES_LINK_HOME": str(root), "HERMES_LINK_STATE_DIR": str(root / "state")}),
                mock.patch.object(sys, "stdout", new_callable=_Capture) as output,
            ):
                bridge_runner.main()

            self.assertIn("routing policy blocked", output.value)
            self.assertFalse((root / "state" / "session-map.json").exists())


class _Capture:
    def __init__(self) -> None:
        self.value = ""

    def write(self, value: str) -> int:
        self.value += value
        return len(value)

    def flush(self) -> None:
        return None


def _write_repo_shape(root: Path, *, policy_block: bool = False) -> None:
    skill = root / "skills" / "agent-comms" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("Use SEND agent_id: message.", encoding="utf-8")
    config = root / "config" / "org.yaml"
    config.parent.mkdir()
    lines = [
        "agents:",
        "  hl_ceo:",
        "    command: hl_ceo",
        "  hl_advisor:",
        "    command: hl_advisor",
    ]
    if policy_block:
        lines.extend(
            [
                "routing:",
                "  deny:",
                "    hl_ceo:",
                "      - hl_advisor",
            ]
        )
    lines.append("skill: skills/agent-comms/SKILL.md")
    config.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
