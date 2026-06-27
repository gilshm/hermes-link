from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from hermes_link.config import resolve_hermes_home, save_runtime_config
from hermes_link.org import load_org


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ORG = REPO_ROOT / "config" / "org.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Hermes Link agent communication support")
    parser.add_argument("--org", type=Path, default=DEFAULT_ORG)
    parser.add_argument("--hermes-home", type=Path, default=None)
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Hermes profile to install the skill into. Repeat to select multiple profiles and skip the prompt.",
    )
    parser.add_argument("--all", action="store_true", help="Install into all discovered Hermes profiles without prompting.")
    parser.add_argument("--skip-skills", action="store_true")
    parser.add_argument("--skip-plugin", action="store_true")
    parser.add_argument("--skip-plugin-enable", action="store_true")
    parser.add_argument("--skip-wrapper", action="store_true")
    parser.add_argument("--create-profiles", action="store_true", help="Create missing Hermes profiles from org.yaml first.")
    parser.add_argument("--clone-from", help="Profile to clone when creating missing org profiles.")
    args = parser.parse_args(argv)
    hermes_home = _prompt_hermes_home(REPO_ROOT, explicit=args.hermes_home)
    save_runtime_config(REPO_ROOT, hermes_home=str(hermes_home))

    org = load_org(args.org)
    if args.create_profiles:
        for created in create_profiles_from_org(
            org,
            hermes_home=hermes_home,
            clone_from=args.clone_from,
        ):
            print(created)

    profiles = select_profiles(
        hermes_home=hermes_home,
        requested=args.profiles,
        default_profiles=sorted(discover_profiles(hermes_home) or org.agents),
        install_all=args.all,
    )

    if not args.skip_wrapper:
        wrapper = install_wrapper(REPO_ROOT)
        print(f"installed wrapper: {wrapper}")

    if not args.skip_skills:
        for profile in profiles:
            destination = install_skill(
                skill_path=org.skill_path,
                hermes_home=hermes_home,
                profile=profile,
            )
            print(f"installed skill for {profile}: {destination}")

    if not args.skip_plugin:
        for profile in profiles:
            destination = install_plugin(
                plugin_path=REPO_ROOT / ".hermes" / "plugins" / "hermes-link",
                hermes_home=hermes_home,
                profile=profile,
            )
            print(f"installed plugin for {profile}: {destination}")
            if not args.skip_plugin_enable:
                enable_plugin(hermes_home=hermes_home, profile=profile, plugin_name="hermes-link")
                print(f"enabled plugin for {profile}: hermes-link")

    first_agent = next(iter(org.agents))
    print(f"run mediated chats with: bin/hermes_link chat {first_agent} \"...\"")
    return 0


def install_wrapper(repo_root: Path) -> Path:
    bin_dir = repo_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "hermes_link"
    python = repo_root / ".venv" / "bin" / "python"
    python_command = str(python) if python.exists() else "python3"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'cd "{repo_root}"\n'
        f'exec "{python_command}" -m hermes_link.cli "$@"\n',
        encoding="utf-8",
    )
    mode = wrapper.stat().st_mode
    wrapper.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper


def _prompt_hermes_home(repo_root: Path, *, explicit: Path | None) -> Path:
    default_home = resolve_hermes_home(repo_root, explicit=explicit)
    if explicit is not None or not sys.stdin.isatty():
        return default_home
    answer = input(f"Where is Hermes installed? Press Enter for {default_home}: ").strip()
    if not answer:
        return default_home
    return Path(answer).expanduser().resolve()


def create_profiles_from_org(org, *, hermes_home: Path, clone_from: str | None = None) -> list[str]:
    results: list[str] = []
    for name in sorted(org.agents):
        agent = org.agents[name]
        profile = agent.command
        if (hermes_home / "profiles" / profile).exists():
            results.append(f"profile exists: {profile}")
            continue
        args = ["hermes", "profile", "create"]
        if clone_from:
            args.extend(["--clone-from", clone_from])
        else:
            args.append("--clone")
        description = _profile_description(agent)
        if description:
            args.extend(["--description", description])
        args.append(profile)
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            env=_hermes_env(hermes_home),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"failed to create Hermes profile {profile}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        results.append(f"created profile: {profile}")
    return results


def install_skill(*, skill_path: Path, hermes_home: Path, profile: str) -> Path:
    if not skill_path.exists():
        raise FileNotFoundError(f"skill does not exist: {skill_path}")

    destination = hermes_home / "profiles" / profile / "skills" / skill_path.parent.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(skill_path.parent, destination)
    return destination


def install_plugin(*, plugin_path: Path, hermes_home: Path, profile: str) -> Path:
    if not plugin_path.exists():
        raise FileNotFoundError(f"plugin does not exist: {plugin_path}")

    destination = hermes_home / "profiles" / profile / "plugins" / plugin_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(plugin_path, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (destination / "repo_root.txt").write_text(str(REPO_ROOT), encoding="utf-8")
    return destination


def enable_plugin(*, hermes_home: Path, profile: str, plugin_name: str) -> None:
    completed = subprocess.run(
        ["hermes", "-p", profile, "plugins", "enable", plugin_name],
        check=False,
        capture_output=True,
        text=True,
        env=_hermes_env(hermes_home),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"failed to enable plugin {plugin_name} for {profile}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def discover_profiles(hermes_home: Path) -> list[str]:
    profiles_dir = hermes_home / "profiles"
    if not profiles_dir.exists():
        return []
    return sorted(path.name for path in profiles_dir.iterdir() if path.is_dir())


def _hermes_env(hermes_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    return env


def select_profiles(
    *,
    hermes_home: Path,
    requested: list[str] | None,
    default_profiles: list[str],
    install_all: bool,
) -> list[str]:
    available = discover_profiles(hermes_home)
    if requested:
        _validate_requested_profiles(requested, available)
        return requested
    if install_all or not sys.stdin.isatty():
        return default_profiles

    print("Available Hermes profiles:")
    for index, profile in enumerate(available, start=1):
        print(f"  {index}. {profile}")
    answer = input(
        "Install agent-comms skill into which profiles? "
        "Press Enter for all, or enter comma-separated names/numbers: "
    ).strip()
    if not answer:
        return default_profiles

    selected = _parse_profile_selection(answer, available)
    _validate_requested_profiles(selected, available)
    return selected


def _parse_profile_selection(answer: str, available: list[str]) -> list[str]:
    selected: list[str] = []
    for item in (part.strip() for part in answer.split(",")):
        if not item:
            continue
        if item.isdigit():
            index = int(item)
            if index < 1 or index > len(available):
                raise ValueError(f"profile selection index out of range: {item}")
            selected.append(available[index - 1])
        else:
            selected.append(item)
    if not selected:
        raise ValueError("no profiles selected")
    return selected


def _validate_requested_profiles(requested: list[str], available: list[str]) -> None:
    if not available:
        return
    missing = sorted(set(requested) - set(available))
    if missing:
        raise ValueError(f"unknown Hermes profile(s): {', '.join(missing)}")


def _profile_description(agent) -> str:
    parts = []
    if agent.title:
        parts.append(agent.title)
    if agent.team:
        parts.append(f"{agent.team} team")
    if agent.capabilities:
        parts.append(f"Capabilities: {', '.join(agent.capabilities)}.")
    if agent.expertise:
        parts.append(agent.expertise)
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
