import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link import bridge_runner
from hermes_link import handoff_runner


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
                "from_agent": "hl_advisor",
                "to": "hl_backend_engineer",
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

    def test_bridge_handoff_mode_starts_worker_and_returns_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_repo_shape(root)

            payload = {
                "from_agent": "hl_ceo",
                "to": "hl_cto",
                "body": "take over",
                "mode": "handoff",
                "source_session_id": "session-a",
            }
            with (
                mock.patch("sys.stdin.read", return_value=json.dumps(payload)),
                mock.patch.dict(os.environ, {"HERMES_LINK_HOME": str(root), "HERMES_LINK_STATE_DIR": str(root / "state")}),
                mock.patch("hermes_link.bridge_runner.subprocess.Popen") as popen,
                mock.patch.object(sys, "stdout", new_callable=_Capture) as output,
            ):
                bridge_runner.main()

            self.assertIn("Handoff accepted.", output.value)
            self.assertIn("Thread id: session-a.", output.value)
            self.assertIn("hl_cto owns the conversation now.", output.value)
            popen.assert_called_once()
            self.assertIn("hermes_link.handoff_runner", popen.call_args.args[0])
            events = (root / "state" / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "handoff"', events)
            payloads = list((root / "state" / "handoffs").glob("session-a.json"))
            self.assertEqual(len(payloads), 1)
            handoff_payload = json.loads(payloads[0].read_text(encoding="utf-8"))
            self.assertEqual(handoff_payload["from_agent"], "hl_ceo")
            self.assertEqual(handoff_payload["to_agent"], "hl_cto")

    def test_bridge_rejects_unknown_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_repo_shape(root)
            payload = {
                "from_agent": "hl_ceo",
                "to": "hl_cto",
                "body": "take over",
                "mode": "unknown",
            }
            with (
                mock.patch("sys.stdin.read", return_value=json.dumps(payload)),
                mock.patch.dict(os.environ, {"HERMES_LINK_HOME": str(root)}),
                self.assertRaisesRegex(ValueError, "mode must be send or handoff"),
            ):
                bridge_runner.main()

    def test_handoff_worker_calls_target_as_final_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_repo_shape(root)
            payload_path = root / "state" / "handoffs" / "session-a.json"
            payload_path.parent.mkdir(parents=True)
            payload_path.write_text(
                json.dumps(
                    {
                        "repo_root": str(root),
                        "state_dir": str(root / "state"),
                        "log_path": str(root / "state" / "events.jsonl"),
                        "from_agent": "hl_ceo",
                        "to_agent": "hl_cto",
                        "body": "take over",
                        "max_messages": 4,
                        "source_session_id": "session-a",
                        "thread_id": "session-a",
                    }
                ),
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout="session_id: cto-session\nhandoff final", stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                handoff_runner.main([str(payload_path)])

            self.assertEqual([call[0] for call in calls], ["hl_cto"])
            self.assertIn("handed this conversation off", calls[0][-1])
            self.assertIn("You now own the conversation", calls[0][-1])
            events = (root / "state" / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "final"', events)
            session_map = (root / "state" / "session-map.json").read_text(encoding="utf-8")
            self.assertIn("cto-session", session_map)


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
        "    manager: hl_ceo",
        "  hl_cto:",
        "    command: hl_cto",
        "    manager: hl_ceo",
        "  hl_backend_engineer:",
        "    command: hl_backend_engineer",
        "    manager: hl_cto",
    ]
    if policy_block:
        lines.extend(
            [
                "routing: strict_hierarchical",
            ]
        )
    lines.append("skill: skills/agent-comms/SKILL.md")
    config.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
