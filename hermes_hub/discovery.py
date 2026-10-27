"""Find local Hermes profiles.

First choice is `hermes profile list`; if hermes is missing, fails or prints
nothing parseable, fall back to the directories under ~/.hermes/profiles/
(plus `default`). Nothing here writes to ~/.hermes.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SEPARATOR_CHARS = set("─━-=═ \t")
ACTIVE_MARKERS = "◆*●►>→"

# Runs an argv and returns (returncode, stdout). Swappable for tests.
Runner = Callable[[list[str]], tuple[int, str]]


def hermes_bin() -> str:
    return os.environ.get("HERMES_HUB_HERMES", "hermes")


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def default_runner(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "NO_COLOR": "1"},
    )
    return proc.returncode, proc.stdout


def parse_profile_list(output: str) -> list[str]:
    """Extract profile names from `hermes profile list` output.

    Handles the table form (header row, box-drawing separator, one row per
    profile with the active one marked by ◆) as well as a plain one-name-per-line list.
    """
    lines = [ANSI_RE.sub("", l).rstrip() for l in output.splitlines()]
    lines = [l for l in lines if l.strip()]
    sep = next((i for i, l in enumerate(lines) if set(l) <= SEPARATOR_CHARS), None)
    if sep is not None:
        rows = lines[sep + 1 :]
    else:
        rows = [l for l in lines if l.split()[0].lower() not in ("profile", "profiles", "name")]
    names: list[str] = []
    for row in rows:
        token = row.strip().lstrip(ACTIVE_MARKERS).strip()
        if not token:
            continue
        name = token.split()[0]
        if PROFILE_RE.match(name) and name not in names:
            names.append(name)
    return names


def profiles_from_disk(home: Path | None = None) -> list[str]:
    home = home or hermes_home()
    names = ["default"]
    try:
        entries = sorted(p.name for p in (home / "profiles").iterdir() if p.is_dir())
    except OSError:
        entries = []
    for n in entries:
        if PROFILE_RE.match(n) and n not in names:
            names.append(n)
    return names


def list_profiles(runner: Runner | None = None, home: Path | None = None) -> list[str]:
    runner = runner or default_runner
    try:
        code, out = runner([hermes_bin(), "profile", "list"])
    except (OSError, subprocess.SubprocessError):
        code, out = 1, ""
    if code == 0:
        names = parse_profile_list(out)
        if names:
            return names
    return profiles_from_disk(home)
