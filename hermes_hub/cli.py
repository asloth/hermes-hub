"""`hh`: pick a Hermes profile or remote peer and talk to it.

Exit codes: 0 ok, 1 error (failed child, unreadable config), 2 usage error.
Errors are a single line on stderr; tracebacks only with HERMES_HUB_DEBUG=1.
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
from typing import Callable, TextIO

from hermes_hub import HubError, UsageError, __version__, config
from hermes_hub.resolve import Agent, Catalog, build_command

EPILOG = """\
commands:
  hh                         numbered list of profiles and remotes; pick one to chat
  hh list                    print the list and exit
  hh chat <agent>            chat with an agent directly
  hh ask <agent> "<prompt>"  one-shot question, prints only the reply ('-' reads stdin)
  hh remote add <name> <agent> | list | remove <name>
  hh mcp                     stdio MCP server for Claude Code (needs the 'mcp' package)
  hh --print-command <agent> [-q "<prompt>"]
                             print the hermes argv instead of running it

<agent> is a local profile, a remote name from the config, or <peer>/<agent>.
"""


class Parser(argparse.ArgumentParser):
    def error(self, message: str):  # one line, exit 2
        raise UsageError(f"{message} (see '{self.prog} --help')")


def build_parser() -> Parser:
    p = Parser(
        prog="hh",
        description="One terminal front-end for your Hermes profiles and peers.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"hh {__version__}")
    p.add_argument("--print-command", metavar="AGENT", help="print the exact hermes argv for AGENT and exit")
    p.add_argument("-q", "--query", metavar="PROMPT", help="with --print-command: the one-shot prompt")
    sub = p.add_subparsers(dest="command", metavar="<command>")
    sub.add_parser("list", aliases=["ls"], help="list profiles and remotes")
    c = sub.add_parser("chat", help="chat with an agent")
    c.add_argument("agent")
    a = sub.add_parser("ask", help="one-shot question; prints only the reply")
    a.add_argument("agent")
    a.add_argument("prompt", nargs="?", default="-", help="prompt text, or '-' (default) to read stdin")
    r = sub.add_parser("remote", help="manage remote peers in the config")
    rsub = r.add_subparsers(dest="remote_command", metavar="<add|list|remove>", required=True)
    ra = rsub.add_parser("add", help="add a remote (peer registered with 'hermes peer add')")
    ra.add_argument("name", help="peer name as registered with 'hermes peer add'")
    ra.add_argument("agent", help="agent/profile served on that peer")
    rsub.add_parser("list", aliases=["ls"], help="list remotes")
    rr = rsub.add_parser("remove", aliases=["rm"], help="remove a remote")
    rr.add_argument("name")
    sub.add_parser("mcp", help="run the stdio MCP server for Claude Code")
    return p


# --- running hermes -------------------------------------------------------


def run_hermes(argv: list[str], stdin=None) -> None:
    """Run hermes in the foreground. Ctrl-C goes to the child, not to us."""
    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        code = subprocess.run(argv, stdin=stdin).returncode
    except FileNotFoundError:
        raise HubError(f"'{argv[0]}' not found on PATH; is Hermes installed?")
    finally:
        signal.signal(signal.SIGINT, old)
    if code != 0:
        raise HubError(f"{shlex.join(argv[:4])} exited with status {code}")


def run_hermes_reply(argv: list[str], stdin=None) -> None:
    """Run hermes for a one-shot and print only the assistant reply.

    hermes -Q prints the reply plus a trailing `session_id:` line for scripting; strip that
    and any legacy session footer so `hh ask` output can be piped into another agent.
    """
    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        done = subprocess.run(argv, stdin=stdin, capture_output=True, text=True)
    except FileNotFoundError:
        raise HubError(f"'{argv[0]}' not found on PATH; is Hermes installed?")
    finally:
        signal.signal(signal.SIGINT, old)
    if done.returncode != 0:
        if done.stderr.strip():
            print(done.stderr.rstrip(), file=sys.stderr)
        raise HubError(f"{shlex.join(argv[:4])} exited with status {done.returncode}")
    lines = done.stdout.splitlines()
    cut = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("session_id:") or line.startswith("Resume this session with:") \
                or line.startswith("Session:") or line.startswith("Title:") \
                or line.startswith("Duration:") or line.startswith("Messages:"):
            cut = i
            break
    reply = "\n".join(lines[:cut]).rstrip()
    if reply:
        print(reply)


def chat(agent: Agent, input_fn: Callable[[str], str] | None = None, out: TextIO | None = None) -> None:
    input_fn, out = input_fn or input, out or sys.stdout
    if agent.kind == "local":
        run_hermes(build_command(agent))
        return
    # Remote: hermes has no remote TUI; each line becomes one `hermes peer dm`.
    print(f"{agent.peer_target} via hermes peer. /exit or Ctrl-D to quit.", file=out)
    while True:
        try:
            line = input_fn(f"{agent.peer_target}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            return
        if line in ("/exit", "/quit"):
            return
        if not line:
            continue
        try:
            run_hermes(build_command(agent, line), stdin=subprocess.DEVNULL)
        except HubError as e:
            print(f"hh: {e}", file=sys.stderr)


def pick(
    catalog: Catalog, input_fn: Callable[[str], str] | None = None, out: TextIO | None = None
) -> Agent | None:
    input_fn, out = input_fn or input, out or sys.stdout
    agents = catalog.agents()
    print_list(agents, out)
    while True:
        try:
            choice = input_fn(f"\nPick [1-{len(agents)}, q to quit]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            return None
        if choice.lower() in ("", "q", "quit", "exit"):
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(agents):
            return agents[int(choice) - 1]
        try:
            return catalog.resolve(choice)
        except UsageError:
            print(f"  no such agent: {choice}", file=out)


def print_list(agents: list[Agent], out: TextIO | None = None) -> None:
    out = out or sys.stdout
    width = max((len(a.name) for a in agents), default=0)
    for i, a in enumerate(agents, 1):
        print(f"{i:>3}  {a.name:<{width}}  {a.describe()}", file=out)


# --- entry point ----------------------------------------------------------


def dispatch(args: argparse.Namespace) -> int:
    if args.print_command is not None:
        if args.command:
            raise UsageError("--print-command cannot be combined with a command")
        agent = Catalog.discover().resolve(args.print_command)
        print(shlex.join(build_command(agent, args.query)))
        return 0
    if args.query is not None:
        raise UsageError("-q/--query is only valid with --print-command (use 'hh ask')")

    if args.command == "remote":
        return remote_cmd(args)
    if args.command == "mcp":
        from hermes_hub import mcp_server

        mcp_server.serve()
        return 0

    catalog = Catalog.discover()
    if args.command in ("list", "ls"):
        print_list(catalog.agents())
    elif args.command == "chat":
        chat(catalog.resolve(args.agent))
    elif args.command == "ask":
        agent = catalog.resolve(args.agent)
        prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
        if not prompt.strip():
            raise UsageError("empty prompt")
        run_hermes_reply(build_command(agent, prompt.strip()), stdin=subprocess.DEVNULL)
    else:
        agent = pick(catalog)
        if agent is not None:
            chat(agent)
    return 0


def remote_cmd(args: argparse.Namespace) -> int:
    sub = args.remote_command
    if sub == "add":
        r = config.add_remote(args.name, args.agent)
        print(f"added remote {r.name} -> hermes peer dm {r.target}  ({config.config_path()})")
    elif sub in ("list", "ls"):
        remotes = config.load()
        if not remotes:
            print(f"no remotes ({config.config_path()})")
        for r in remotes:
            print(f"{r.name}\t{r.target}")
    else:
        config.remove_remote(args.name)
        print(f"removed remote {args.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return dispatch(args)
    except HubError as e:
        print(f"hh: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print("hh: interrupted", file=sys.stderr)
        return 1
    except Exception as e:  # never a traceback for the user
        if os.environ.get("HERMES_HUB_DEBUG"):
            raise
        print(f"hh: unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
