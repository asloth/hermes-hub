import subprocess
import sys

import pytest

from hermes_hub import mcp_server

from conftest import PROFILES, ROOT, subprocess_env


@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="  the reply\n", stderr="")

    monkeypatch.setattr(mcp_server.subprocess, "run", run)
    return calls


def test_list_agents_returns_discovered_profiles(config_file):
    agents = mcp_server.list_agents()
    assert [a["name"] for a in agents if a["kind"] == "local"] == PROFILES
    assert {"name": "vps", "kind": "remote", "peer": "vps", "agent": "viaje"} in agents


def test_list_agents_without_config():
    assert [a["name"] for a in mcp_server.list_agents()] == PROFILES


def test_ask_agent_local_builds_oneshot_call(fake_run):
    assert mcp_server.ask_agent("finance", "saldo?") == "the reply"
    argv, kwargs = fake_run[0]
    assert argv == ["hermes", "-p", "finance", "chat", "-q", "saldo?", "--oneshot", "-Q"]
    # stdin/stdout carry the MCP protocol: the child must not inherit them.
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["capture_output"] is True


def test_ask_agent_remote_uses_peer_dm(fake_run, config_file):
    mcp_server.ask_agent("vps", "itinerario?")
    assert fake_run[0][0] == ["hermes", "peer", "dm", "vps/viaje", "itinerario?"]


def test_ask_agent_unknown(fake_run):
    with pytest.raises(ValueError, match="unknown agent 'nope'"):
        mcp_server.ask_agent("nope", "hi")
    with pytest.raises(ValueError, match="empty"):
        mcp_server.ask_agent("coach", "  ")
    assert fake_run == []


def test_ask_agent_child_failure(monkeypatch):
    monkeypatch.setattr(
        mcp_server.subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom\npeer unreachable\n"),
    )
    with pytest.raises(RuntimeError, match=r"coach failed \(exit 1\): peer unreachable"):
        mcp_server.ask_agent("coach", "hi")


def test_server_registers_both_tools():
    pytest.importorskip("mcp")
    import asyncio

    tools = asyncio.run(mcp_server.build_server().list_tools())
    tools = getattr(tools, "tools", tools)
    assert sorted(t.name for t in tools) == ["ask_agent", "list_agents"]


def test_stdio_handshake_and_list_agents(fake_hermes_bin, tmp_path, config_file):
    """Speak raw JSON-RPC to `hh mcp` the way Claude Code does."""
    pytest.importorskip("mcp")
    import json

    bindir, _ = fake_hermes_bin
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "list_agents", "arguments": {}}},
    ]
    proc = subprocess.Popen(
        [sys.executable, "-m", "hermes_hub", "mcp"],
        env=subprocess_env(bindir, tmp_path), text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    replies = {}
    try:
        for m in msgs:  # keep stdin open until each reply arrives, like a real client
            proc.stdin.write(json.dumps(m) + "\n")
            proc.stdin.flush()
            while "id" in m and m["id"] not in replies:
                line = proc.stdout.readline()
                assert line, "server closed stdout"
                reply = json.loads(line)
                replies[reply.get("id")] = reply
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    assert replies[1]["result"]["serverInfo"]["name"] == "hermes-hub"
    assert sorted(t["name"] for t in replies[2]["result"]["tools"]) == ["ask_agent", "list_agents"]
    result = replies[3]["result"]
    assert not result.get("isError")
    text = " ".join(c["text"] for c in result["content"])  # one content block per agent
    for name in PROFILES + ["vps"]:
        assert f'"name": "{name}"' in text


def _run_without_mcp(code):
    """Run code in a fresh interpreter where `import mcp` fails."""
    prelude = "import sys; sys.modules['mcp'] = None\n"
    return subprocess.run(
        [sys.executable, "-c", prelude + code], cwd=ROOT, capture_output=True, text=True
    )


def test_hh_works_without_mcp_package():
    p = _run_without_mcp(
        "from hermes_hub import cli, mcp_server\n"
        "assert 'mcp' not in [m for m in sys.modules if sys.modules[m] is not None]\n"
        "sys.exit(cli.main(['--help']))\n"
    )
    assert p.returncode == 0, p.stderr
    assert "usage: hh" in p.stdout


def test_hh_mcp_without_package_is_one_line_error():
    p = _run_without_mcp("from hermes_hub import cli\nsys.exit(cli.main(['mcp']))\n")
    assert p.returncode == 1
    assert p.stderr == "hh: the 'mcp' package is not installed; run: pipx inject hermes-hub mcp\n"
