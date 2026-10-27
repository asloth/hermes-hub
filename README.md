# hermes-hub

`hh` gives you one terminal entry point for all your Hermes agents. It lists every local
profile and every configured remote peer, lets you pick one by number, and drops you into
its chat. It also bridges Hermes and Claude Code in both directions.

`hh` only wraps commands that already exist. It does not reimplement chat or transport:

| You do                         | `hh` runs                                         |
|--------------------------------|---------------------------------------------------|
| pick a local profile           | `hermes -p <profile> chat`                        |
| `hh ask <profile> "..."`       | `hermes -p <profile> chat -q "..." --oneshot`     |
| pick / ask a remote            | `hermes peer dm <peer>/<agent> "..."`             |

It uses only the Python 3.10+ standard library. The `mcp` package is optional and only
needed for `hh mcp`.

## Install

```sh
pipx install .                 # from this directory
pipx inject hermes-hub mcp     # optional: only needed for `hh mcp` (Claude Code bridge)
```

You can also install both at once with `pipx install '.[mcp]'`.

## First run

```sh
hh
```

```
  1  default  local profile
  2  coach    local profile
  3  dev      local profile
  4  finance  local profile
  5  twitter  local profile
  6  viaje    local profile
  7  vps      remote via hermes peer -> vps/viaje

Pick [1-7, q to quit]: 2
```

You can type a number or a name. Picking a local profile runs `hermes -p coach chat` in the
foreground with your terminal attached. It is the normal Hermes chat, and Ctrl-C goes to
Hermes, not to `hh`.
Picking a remote opens a simple line prompt: each line you type is sent with
`hermes peer dm vps/viaje "<line>"` and the reply is printed. Type `/exit` or press Ctrl-D
to leave.

Profiles are discovered with `hermes profile list`. If that fails, `hh` falls back to the
directories under `~/.hermes/profiles/` plus `default`. Nothing is hardcoded.

### Commands

```sh
hh                              # numbered picker
hh list                         # print the list and exit
hh chat <agent>                 # skip the picker
hh ask <agent> "<prompt>"       # one-shot, prints only the reply; "-" or no prompt reads stdin
hh remote add <name> <agent>    # add a remote peer
hh remote list
hh remote remove <name>
hh mcp                          # stdio MCP server for Claude Code
hh --print-command <agent> [-q "<prompt>"]   # print the exact hermes argv, run nothing
```

`<agent>` can be a local profile, a remote name from the config, or an explicit
`<peer>/<agent>`. If a name is both a local profile and a remote, `hh` refuses to guess
and asks you to use `<peer>/<agent>` for the remote.

Exit codes are `0` for success, `1` for an error (hermes missing, hermes exited non-zero,
or an unreadable config), and `2` for a usage error (unknown agent, bad arguments).
Errors are printed as a single line on stderr. Set `HERMES_HUB_DEBUG=1` to get a
traceback for unexpected errors.

## Remote setup (via `hermes peer`)

Hermes has no supported way to point a TUI at a remote gateway, so `hh` never tries to.
Instead, the remote gateway is registered as a Hermes **peer**:

1. **On the VPS**, enable the `api_server` platform on the gateway that serves your
   profiles (see the Hermes docs), and note its URL and `API_SERVER_KEY`.
2. **On your machine**, register it with Hermes. Hermes stores the key in
   `~/.hermes/.env`; `hh` never sees it.
   ```sh
   hermes peer add vps --url http://<vps-host>:8377 --key <API_SERVER_KEY>
   hermes peer list
   hermes peer dm vps/viaje "ping"      # check it answers
   ```
3. **Tell `hh` about it:**
   ```sh
   hh remote add vps viaje
   ```
   This writes `~/.config/hermes-hub/config.toml` (or `$XDG_CONFIG_HOME/hermes-hub/`):
   ```toml
   [[remote]]
   name = "vps"
   agent = "viaje"        # the agent/profile served on that peer
   ```
   To reach several agents on the same peer, use `hh ask vps/coach "..."` directly. The
   config holds one entry per remote name.

Only `name` and `agent` are allowed in the config. `hh` rejects `url`, `key`, `token` and
any other key, so credentials stay with `hermes peer`. If the file is missing, `hh` treats
it as "no remotes".

## Claude Code ↔ Hermes

**Hermes from Claude Code (MCP).** `hh mcp` starts a stdio MCP server with two tools:

- `list_agents()` returns every local profile and remote, as `{name, kind, ...}`.
- `ask_agent(agent, prompt)` runs the agent one-shot and returns its reply. It uses the
  same resolver and commands as the CLI.

To wire it up:

```sh
claude mcp add hermes-hub -- hh mcp
```

or add it to a project's `.mcp.json`:

```json
{
  "mcpServers": {
    "hermes-hub": {
      "command": "hh",
      "args": ["mcp"]
    }
  }
}
```

If Claude Code can't find `hh` on its PATH, use the absolute path, for example
`~/.local/bin/hh`. Then ask Claude something like "ask my finance agent what I spent on
travel this month".

**Claude Code from a shell, or Hermes from anywhere.** `hh ask` prints only the reply, so
you can pipe it or call it from a script or tool:

```sh
hh ask coach "summarise today's plan" | tee plan.txt
git diff | hh ask dev -
```

## Environment

| Variable            | Purpose                                                   |
|---------------------|-----------------------------------------------------------|
| `HERMES_HUB_CONFIG` | Config file path (default `~/.config/hermes-hub/config.toml`) |
| `HERMES_HUB_HERMES` | hermes executable to run (default `hermes` on PATH)       |
| `HERMES_HOME`       | Where to look for `profiles/` when `hermes profile list` fails |
| `HERMES_HUB_DEBUG`  | Show tracebacks for unexpected errors                     |

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install pytest   # add `mcp` to also run the MCP server tests
make test                                               # = .venv/bin/python -m pytest -q
```

The tests never run the real `hermes`. Discovery is fed captured `hermes profile list`
output. The end-to-end tests put a fake `hermes` on PATH that only answers `profile list`.
Command building is checked through `hh --print-command`.
