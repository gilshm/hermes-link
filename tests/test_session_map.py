import tempfile
import unittest
from pathlib import Path

from hermes_link.session_map import SessionMap


class SessionMapTests(unittest.TestCase):
    def test_get_and_set_target_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_map = SessionMap(Path(tmpdir) / "session-map.json")

            self.assertIsNone(session_map.get(source_session_id="source-a", agent="agent_b"))
            session_map.set(
                source_session_id="source-a",
                agent="agent_b",
                target_session_id="session-b",
            )

            self.assertEqual(
                session_map.get(source_session_id="source-a", agent="agent_b"),
                "session-b",
            )
            self.assertEqual(session_map.entries(), [("source-a", "agent_b", "session-b")])


if __name__ == "__main__":
    unittest.main()
