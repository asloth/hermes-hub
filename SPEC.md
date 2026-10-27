# hermes-hub — SPEC

A terminal front-end for Hermes that feels like the Claude Code CLI, so Sara can work with
all her profiles from one place, attach to a remote Hermes, and let a Hermes profile talk to
Claude Code (and vice versa) without leaving the terminal.

## Problem

Sara runs several Hermes profiles (`default`, `coach`, `finance`, `dev`, `twitter`, `viaje`)
served by one gateway on a VPS. Today she has to remember `hermes -p <profile> chat`, and there
is no single place that shows what exists, what is remote, or how to hand a task from one agent
to another. Claude Code has a CLI she likes; Hermes does not have its equivalent front-end.

## Hard requirements

1. **One command, `hh`, that lists every profile and every configured remote** and lets her pick
   one with a number, then drops into that profile's chat.
2. **Local launch** must be exactly `hermes -p <profile> chat` (interactive) or
   `hermes -p <profile> chat -q "<query>" --oneshot` for one-shot. Do not reimplement chat.
3. **Remote targets are Hermes peers, not a TUI attach.** Hermes has no supported "point a TUI at
   a remote gateway" mode (`HERMES_TUI_GATEWAY_URL` is dashboard-internal and must not be used).
   The supported route is `hermes peer`: the VPS gateway runs the `api_server` platform and is
   registered locally with `hermes peer add`, so the CLI can message a remote agent with
   `hermes peer dm <peer>/<agent> "<prompt>"` and print the reply. `hh` wraps that command and
   never reimplements the transport.
4. **Config file** `~/.config/hermes-hub/config.toml`:
   ```toml
   [[remote]]
   name = "vps"
   agent = "viaje"        # the agent/profile served on that peer
   ```
   `hh remote add <name> <agent>` and `hh remote list` manage it. Remotes are listed alongside
   local profiles; picking one runs `hermes peer dm <name>/<agent> "<prompt>"`. Missing file
   means "no remotes". Do not store URLs, keys or tokens.
5. **Bridge to Claude Code**: `hh ask <agent> "<prompt>"` runs that Hermes profile one-shot
   (`hermes -p <profile> chat -q ... --oneshot`) and prints only the reply; for a remote agent it
   uses `hermes peer dm`. And `hh mcp` starts a stdio MCP server exposing `list_agents()` and
   `ask_agent(agent, prompt)`, so Claude Code can ask any of her agents directly. The MCP tools
   call the same resolver as the CLI.
6. **Discovery**: profiles come from `hermes profile list` when available, else from directories
   under `~/.hermes/profiles/` (plus `default`). No hardcoded list of Sara's profiles.
7. **No new runtime dependencies**: Python 3.10+ standard library only. The MCP server may
   import the `mcp` package if it is already installed, but `hh` must work without it.
8. **Exit codes**: 0 ok, 1 error (bad profile, failed child), 2 usage error. Errors go to stderr
   in one line, no tracebacks.

## Acceptance tests (must exist and pass)

- `tests/test_config.py`: parse/round-trip the TOML config, reject duplicate remote names, handle
  a missing file.
- `tests/test_resolve.py`: given fake `hermes profile list` output and a config, produce the right
  command for local and remote targets; unknown profile is exit 2 with a message.
- `tests/test_cli.py`: `hh --print-command <target>` prints the exact argv it would exec (this is
  how the tests avoid spawning hermes), for local and remote.
- `tests/test_mcp.py`: `list_agents()` returns the discovered profiles; `ask_agent` builds the
  right subprocess call (monkeypatched, no real hermes run).
- A `make test` (or `python -m pytest -q`) that runs everything headless.

## Non-goals

- No new TUI framework, no curses, no rich dependency.
- No changes to Hermes itself: `hh` is a wrapper.
- No credential handling: it never reads tokens or writes to `~/.hermes/.env`.

## Deliverable

A pipx-installable package named `hermes-hub` exposing `hh`, with README (install, first run,
remote setup, Claude Code MCP wiring example), the tests above, and a passing run of them.
