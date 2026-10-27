import shlex
import subprocess
import sys

import pytest

from hermes_hub import cli, config
from hermes_hub.resolve import Catalog

from conftest import PROFILES, subprocess_env


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def no_spawn(monkeypatch):
    """Fail loudly if the CLI tries to run anything other than discovery."""

    def boom(*a, **k):
        raise AssertionError(f"spawned {a}")

    monkeypatch.setattr(cli.subprocess, "run", boom)


def test_print_command_local(capsys, no_spawn):
    assert run(capsys, "--print-command", "coach") == (0, "hermes -p coach chat\n", "")


def test_print_command_local_oneshot(capsys, no_spawn):
    code, out, _ = run(capsys, "--print-command", "dev", "-q", "what's up?")
    assert code == 0
    assert shlex.split(out) == ["hermes", "-p", "dev", "chat", "-q", "what's up?", "--oneshot", "-Q"]


def test_print_command_remote(capsys, config_file, no_spawn):
    code, out, _ = run(capsys, "--print-command", "vps", "-q", "hola")
    assert (code, out) == (0, "hermes peer dm vps/viaje hola\n")
    assert run(capsys, "--print-command", "vps")[1] == "hermes peer dm vps/viaje\n"
    assert run(capsys, "--print-command", "spark/dev", "-q", "hi")[1] == "hermes peer dm spark/dev hi\n"


def test_print_command_unknown_is_exit_2_one_line(capsys, no_spawn):
    code, out, err = run(capsys, "--print-command", "nope")
    assert code == 2 and out == ""
    assert err.startswith("hh: unknown agent 'nope'") and err.count("\n") == 1


def test_usage_errors_are_one_line_exit_2(capsys):
    for argv in (["bogus"], ["ask"], ["remote"], ["-q", "x"], ["--print-command", "coach", "list"]):
        code, out, err = run(capsys, *argv)
        assert code == 2, argv
        assert err.startswith("hh: ") and err.count("\n") == 1, (argv, err)
        assert "Traceback" not in err


def test_failed_child_is_exit_1(capsys, monkeypatch):
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 3, "", ""))
    code, _, err = run(capsys, "ask", "coach", "hi")
    assert code == 1
    assert err == "hh: hermes -p coach chat exited with status 3\n"


def test_missing_hermes_is_exit_1(capsys, monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("hermes")

    monkeypatch.setattr(cli.subprocess, "run", missing)
    code, _, err = run(capsys, "chat", "coach")
    assert code == 1 and "not found on PATH" in err and err.count("\n") == 1


def test_ask_runs_oneshot_and_remote(capsys, config_file, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda argv, **k: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "reply\n", "")
    )
    assert run(capsys, "ask", "coach", "plan my week")[0] == 0
    assert run(capsys, "ask", "vps", "itinerario?")[0] == 0
    assert calls == [
        ["hermes", "-p", "coach", "chat", "-q", "plan my week", "--oneshot", "-Q"],
        ["hermes", "peer", "dm", "vps/viaje", "itinerario?"],
    ]


def test_unexpected_exception_has_no_traceback(capsys, monkeypatch):
    monkeypatch.setattr(cli, "dispatch", lambda args: 1 / 0)
    code, _, err = run(capsys, "list")
    assert code == 1 and err == "hh: unexpected error: ZeroDivisionError: division by zero\n"


def test_list(capsys, config_file):
    code, out, _ = run(capsys, "list")
    lines = out.splitlines()
    assert code == 0 and len(lines) == len(PROFILES) + 1
    assert lines[0].split()[:2] == ["1", "default"]
    assert lines[-1].split()[:2] == ["7", "vps"] and "vps/viaje" in lines[-1]


def test_remote_add_list_remove(capsys):
    assert run(capsys, "remote", "list")[1].startswith("no remotes")
    assert run(capsys, "remote", "add", "vps", "viaje")[0] == 0
    code, _, err = run(capsys, "remote", "add", "vps", "coach")
    assert code == 1 and "already exists" in err
    assert run(capsys, "remote", "list")[1] == "vps\tvps/viaje\n"
    assert config.load() == [config.Remote("vps", "viaje")]
    assert run(capsys, "remote", "rm", "vps")[0] == 0
    assert run(capsys, "remote", "rm", "vps")[0] == 2


def test_picker_by_number_and_name(config_file):
    cat = Catalog.discover(config_file=config_file)
    answers = iter(["99", "2"])
    assert cat.agents()[1] == cli.pick(cat, lambda _: next(answers), out=_Sink())
    assert cli.pick(cat, lambda _: "vps", out=_Sink()).peer_target == "vps/viaje"
    assert cli.pick(cat, lambda _: "q", out=_Sink()) is None

    def eof(_):
        raise EOFError

    assert cli.pick(cat, eof, out=_Sink()) is None


def test_no_args_picks_then_launches_local_chat(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("builtins.input", lambda _: "3")
    monkeypatch.setattr(
        cli.subprocess, "run", lambda argv, **k: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "reply\n", "")
    )
    assert cli.main([]) == 0
    assert calls == [["hermes", "-p", "dev", "chat"]]


def test_remote_chat_sends_each_line_via_peer_dm(monkeypatch, config_file):
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda argv, **k: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "reply\n", "")
    )
    lines = iter(["hola", "", "y mañana?", "/exit"])
    agent = Catalog.discover(config_file=config_file).resolve("vps")
    cli.chat(agent, lambda _: next(lines), out=_Sink())
    assert calls == [
        ["hermes", "peer", "dm", "vps/viaje", "hola"],
        ["hermes", "peer", "dm", "vps/viaje", "y mañana?"],
    ]


def test_end_to_end_with_fake_hermes_on_path(fake_hermes_bin, tmp_path, config_file):
    """Real process, real PATH lookup; the fake hermes only answers `profile list`."""
    bindir, log = fake_hermes_bin
    env = subprocess_env(bindir, tmp_path)

    def hh(*argv):
        return subprocess.run([sys.executable, "-m", "hermes_hub", *argv], env=env, capture_output=True, text=True)

    p = hh("--print-command", "viaje", "-q", "hola")
    assert (p.returncode, p.stdout, p.stderr) == (0, "hermes -p viaje chat -q hola --oneshot -Q\n", "")
    p = hh("--print-command", "vps", "-q", "hola")
    assert (p.returncode, p.stdout) == (0, "hermes peer dm vps/viaje hola\n")
    p = hh("--print-command", "ghost")
    assert p.returncode == 2 and p.stdout == "" and p.stderr.count("\n") == 1
    assert "Traceback" not in p.stderr
    p = hh("ask", "coach", "hi")  # fake hermes exits 99 for anything but profile list
    assert p.returncode == 1 and p.stderr == "hh: hermes -p coach chat exited with status 99\n"
    assert log.read_text().splitlines() == ["profile list"] * 4 + ["-p coach chat -q hi --oneshot -Q"]


class _Sink:
    def write(self, s):
        return len(s)

    def flush(self):
        pass


def test_ask_strips_session_footer(capsys, config_file, monkeypatch):
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, "the reply\n\nsession_id: abc123\n", ""),
    )
    code, out, err = run(capsys, "ask", "coach", "hi")
    assert code == 0
    assert out == "the reply\n"
    assert err == ""
