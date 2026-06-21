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
            EventLog(path).write("message", from_agent="agent_a", to_agent="agent_b", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("agent_a -> agent_b: hello", output.getvalue())


if __name__ == "__main__":
    unittest.main()
