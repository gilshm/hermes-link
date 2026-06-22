import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from install import (
    create_profiles_from_org,
    discover_profiles,
    enable_plugin,
    install_plugin,
    install_skill,
    install_wrapper,
    select_profiles,
)
from hermes_link.org import load_org


class InstallTests(unittest.TestCase):
    def test_install_wrapper_creates_executable_repo_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            wrapper = install_wrapper(repo_root)

            self.assertEqual(wrapper, repo_root / "bin" / "hermes_link")
            self.assertIn('"python3" -m hermes_link.cli', wrapper.read_text(encoding="utf-8"))
            self.assertTrue(wrapper.stat().st_mode & stat.S_IXUSR)

    def test_install_wrapper_prefers_repo_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            python = repo_root / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            wrapper = install_wrapper(repo_root)

            self.assertIn(str(python), wrapper.read_text(encoding="utf-8"))

    def test_install_skill_copies_skill_to_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "repo" / "skills" / "agent-comms" / "SKILL.md"
            source.parent.mkdir(parents=True)
            source.write_text("skill body", encoding="utf-8")
            hermes_home = root / ".hermes"

            destination = install_skill(
                skill_path=source,
                hermes_home=hermes_home,
                profile="hl_ceo",
            )

            self.assertEqual(destination, hermes_home / "profiles" / "hl_ceo" / "skills" / "agent-comms")
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "skill body")

    def test_install_plugin_copies_plugin_to_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "repo" / ".hermes" / "plugins" / "hermes-link"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text("plugin body", encoding="utf-8")
            (source / "plugin.yaml").write_text("name: hermes-link", encoding="utf-8")
            hermes_home = root / ".hermes"

            destination = install_plugin(
                plugin_path=source,
                hermes_home=hermes_home,
                profile="hl_ceo",
            )

            self.assertEqual(destination, hermes_home / "profiles" / "hl_ceo" / "plugins" / "hermes-link")
            self.assertEqual((destination / "__init__.py").read_text(encoding="utf-8"), "plugin body")
            self.assertTrue((destination / "repo_root.txt").read_text(encoding="utf-8"))

    def test_enable_plugin_uses_selected_profile_alias(self) -> None:
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["hl_ceo", "plugins", "enable", "hermes-link"],
                0,
                stdout="enabled",
                stderr="",
            ),
        ) as run:
            enable_plugin(profile="hl_ceo", plugin_name="hermes-link")

        run.assert_called_once_with(
            ["hl_ceo", "plugins", "enable", "hermes-link"],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_discover_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hermes_home = Path(tmpdir)
            (hermes_home / "profiles" / "hl_advisor").mkdir(parents=True)
            (hermes_home / "profiles" / "hl_ceo").mkdir()

            self.assertEqual(discover_profiles(hermes_home), ["hl_advisor", "hl_ceo"])

    def test_select_profiles_uses_all_defaults_when_noninteractive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hermes_home = Path(tmpdir)
            (hermes_home / "profiles" / "hl_ceo").mkdir(parents=True)
            (hermes_home / "profiles" / "hl_advisor").mkdir()

            with mock.patch("sys.stdin.isatty", return_value=False):
                selected = select_profiles(
                    hermes_home=hermes_home,
                    requested=None,
                    default_profiles=["hl_advisor", "hl_ceo"],
                    install_all=False,
                )

            self.assertEqual(selected, ["hl_advisor", "hl_ceo"])

    def test_select_profiles_prompts_for_names_or_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hermes_home = Path(tmpdir)
            (hermes_home / "profiles" / "hl_ceo").mkdir(parents=True)
            (hermes_home / "profiles" / "hl_advisor").mkdir()

            with (
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", return_value="1"),
            ):
                selected = select_profiles(
                    hermes_home=hermes_home,
                    requested=None,
                    default_profiles=["hl_ceo", "hl_advisor"],
                    install_all=False,
                )

            self.assertEqual(selected, ["hl_advisor"])

    def test_create_profiles_from_org_creates_missing_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hermes_home = root / ".hermes"
            org = _write_org(root)

            with mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["hermes"], 0, stdout="created", stderr=""),
            ) as run:
                results = create_profiles_from_org(load_org(org), hermes_home=hermes_home, clone_from="base")

        self.assertEqual(results, ["created profile: hl_advisor", "created profile: hl_ceo"])
        self.assertEqual(run.call_count, 2)
        first = run.call_args_list[0].args[0]
        self.assertEqual(first[:3], ["hermes", "profile", "create"])
        self.assertIn("--clone-from", first)
        self.assertIn("--description", first)

    def test_create_profiles_from_org_skips_existing_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hermes_home = root / ".hermes"
            (hermes_home / "profiles" / "hl_ceo").mkdir(parents=True)
            org = _write_org(root)

            with mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["hermes"], 0, stdout="created", stderr=""),
            ) as run:
                results = create_profiles_from_org(load_org(org), hermes_home=hermes_home)

        self.assertEqual(results, ["created profile: hl_advisor", "profile exists: hl_ceo"])
        run.assert_called_once()
        self.assertIn("--clone", run.call_args.args[0])


def _write_org(root: Path) -> Path:
    skill = root / "skills" / "agent-comms" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill", encoding="utf-8")
    org = root / "config" / "org.yaml"
    org.parent.mkdir()
    org.write_text(
        "\n".join(
            [
                "agents:",
                "  hl_ceo:",
                "    command: hl_ceo",
                "    title: CEO",
                "    team: executive",
                "    expertise: Chief executive",
                "  hl_advisor:",
                "    command: hl_advisor",
                "    title: Advisor",
                "    team: executive",
                "    manager: hl_ceo",
                "    expertise: Strategic reviewer",
                "skill: skills/agent-comms/SKILL.md",
            ]
        ),
        encoding="utf-8",
    )
    return org


if __name__ == "__main__":
    unittest.main()
