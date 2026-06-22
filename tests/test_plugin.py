import importlib.util
import unittest
from pathlib import Path


class PluginTests(unittest.TestCase):
    def test_route_message_schema_exposes_handoff_mode_on_single_tool(self) -> None:
        plugin = _load_plugin()
        schema = plugin.ROUTE_MESSAGE_SCHEMA

        self.assertEqual(schema["name"], "route_message")
        self.assertEqual(schema["parameters"]["properties"]["mode"]["enum"], ["send", "handoff"])
        self.assertEqual(schema["parameters"]["required"], ["from_agent", "to", "body"])


def _load_plugin():
    path = Path(__file__).resolve().parents[1] / ".hermes" / "plugins" / "hermes-link" / "__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_link_plugin", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load plugin module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
