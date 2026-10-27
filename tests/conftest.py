import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermes_hub import discovery  # noqa: E402

# Captured from a real `hermes profile list` (active profile marked with ◆).
PROFILE_LIST_OUTPUT = """\

 Profile          Model                        Gateway      Alias        Distribution
 ───────────────    ───────────────────────────    ───────────    ───────────    ────────────────────
 ◆default         deepseek-v4.1-flash          running      —            —
  coach           deepseek-v4.1-flash          running      coach        —
  dev             kimi-k3.1-pro                running      dev          —
  finance         deepseek-v4.1-flash          running      finance      —
  twitter         deepseek-v4.1-flash          running      twitter      —
  viaje           deepseek-v4.1-flash          running      viaje        —
"""
PROFILES = ["default", "coach", "dev", "finance", "twitter", "viaje"]

CONFIG_TOML = """\
[[remote]]
name = "vps"
agent = "viaje"        # the agent/profile served on that peer
"""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Never touch the real ~/.hermes or ~/.config, never run real hermes."""
    monkeypatch.setenv("HERMES_HUB_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.delenv("HERMES_HUB_HERMES", raising=False)
    monkeypatch.delenv("HERMES_HUB_DEBUG", raising=False)
    calls = []

    def fake_runner(argv):
        calls.append(argv)
        assert argv[1:] == ["profile", "list"], f"unexpected hermes call {argv}"
        return 0, PROFILE_LIST_OUTPUT

    monkeypatch.setattr(discovery, "default_runner", fake_runner)
    return calls


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_TOML)
    return path


@pytest.fixture
def fake_hermes_bin(tmp_path):
    """A `hermes` executable that only answers `profile list` and logs every call."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "hermes-calls.log"
    script = bindir / "hermes"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import sys
            with open({str(log)!r}, "a") as f:
                f.write(" ".join(sys.argv[1:]) + "\\n")
            if sys.argv[1:] == ["profile", "list"]:
                sys.stdout.write({PROFILE_LIST_OUTPUT!r})
                sys.exit(0)
            sys.exit(99)
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bindir, log


def subprocess_env(bindir: Path, tmp_path: Path) -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = str(ROOT)
    env["HERMES_HUB_CONFIG"] = str(tmp_path / "config.toml")
    env["HERMES_HOME"] = str(tmp_path / "hermes-home")
    env.pop("HERMES_HUB_HERMES", None)
    env.pop("HERMES_HUB_DEBUG", None)
    return env
