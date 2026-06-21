import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.cli import main
from hermes_link.log import EventLog


class CliTests(unittest.TestCase):
    def test_log_command_prints_formatted_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="agent_a", to_agent="agent_b", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("[thread-1] ├─ agent_a -> agent_b: hello", output.getvalue())

    def test_log_command_can_force_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="agent_a", to_agent="agent_b", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path), "--color", "always"])

        self.assertEqual(exit_code, 0)
        self.assertIn("\033[", output.getvalue())

    def test_sessions_command_prints_session_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session-map.json"
            path.write_text('{"source-a:agent_b": "session-b"}', encoding="utf-8")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["sessions", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("source-a -> agent_b: session-b", output.getvalue())


if __name__ == "__main__":
    unittest.main()
