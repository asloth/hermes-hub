"""`hh mcp`: stdio MCP server so Claude Code can ask any Hermes agent.

The tools are plain functions over the same resolver the CLI uses. The `mcp`
package is imported only inside serve(), so `hh` works without it.
"""

from __future__ import annotations

import subprocess

from hermes_hub import HubError
from hermes_hub.resolve import Catalog, build_command

ASK_TIMEOUT = 600  # seconds; a Hermes turn can use tools and take a while


def list_agents() -> list[dict]:
    """List Sara's Hermes agents: local profiles and remote peers.

    Each entry has `name` (pass it to ask_agent) and `kind` ("local" or "remote").
    """
    return [a.to_dict() for a in Catalog.discover().agents()]


def ask_agent(agent: str, prompt: str) -> str:
    """Ask one Hermes agent a question and return its reply.

    `agent` is a name from list_agents (a local profile, a remote, or <peer>/<agent>).
    Local profiles run `hermes -p <profile> chat -q <prompt> --oneshot`;
    remotes run `hermes peer dm <peer>/<agent> <prompt>`.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")
    try:
        target = Catalog.discover().resolve(agent)
    except HubError as e:
        raise ValueError(str(e)) from None
    argv = build_command(target, prompt.strip())
    try:
        # stdin/stdout must never be inherited: they carry the MCP protocol.
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=ASK_TIMEOUT,
        )
    except FileNotFoundError:
        raise RuntimeError(f"'{argv[0]}' not found on PATH; is Hermes installed?") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{agent} did not answer within {ASK_TIMEOUT}s") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise RuntimeError(
            f"{agent} failed (exit {proc.returncode})" + (f": {detail[-1]}" if detail else "")
        )
    return proc.stdout.strip()


def _server_class():
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError:
        raise HubError(
            "the 'mcp' package is not installed; run: pipx inject hermes-hub mcp"
        ) from None


def build_server():
    server = _server_class()("hermes-hub")
    server.tool()(list_agents)
    server.tool()(ask_agent)
    return server


def serve() -> None:
    build_server().run()
