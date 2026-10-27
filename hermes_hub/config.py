"""~/.config/hermes-hub/config.toml: the list of remote Hermes peers.

Only two keys are allowed per remote, `name` (the peer registered with
`hermes peer add`) and `agent` (the profile served on that peer). URLs, keys
and tokens belong to `hermes peer`, never to this file.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from hermes_hub import HubError

try:  # Python 3.11+
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.10
    _tomllib = None

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
ALLOWED_KEYS = {"name", "agent"}


class ConfigError(HubError):
    pass


@dataclass(frozen=True)
class Remote:
    name: str
    agent: str

    @property
    def target(self) -> str:
        return f"{self.name}/{self.agent}"


def config_path() -> Path:
    override = os.environ.get("HERMES_HUB_CONFIG")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "hermes-hub" / "config.toml"


def parse(text: str, source: str = "config") -> list[Remote]:
    data = _loads(text, source)
    unknown_top = set(data) - {"remote"}
    if unknown_top:
        raise ConfigError(f"{source}: unknown top-level key(s): {', '.join(sorted(unknown_top))}")
    entries = data.get("remote", [])
    if not isinstance(entries, list):
        raise ConfigError(f"{source}: 'remote' must be an array of tables ([[remote]])")
    remotes: list[Remote] = []
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ConfigError(f"{source}: remote #{i} is not a table")
        extra = set(entry) - ALLOWED_KEYS
        if extra:
            raise ConfigError(
                f"{source}: remote #{i} has unsupported key(s) {', '.join(sorted(extra))}"
                " (only name and agent; credentials live in 'hermes peer')"
            )
        remotes.append(_make_remote(entry.get("name"), entry.get("agent"), f"{source}: remote #{i}"))
    _check_unique(remotes, source)
    return remotes


def dumps(remotes: list[Remote]) -> str:
    out = ["# hermes-hub remotes. Peers are registered with 'hermes peer add'.", ""]
    for r in remotes:
        out += ["[[remote]]", f"name = {_quote(r.name)}", f"agent = {_quote(r.agent)}", ""]
    return "\n".join(out)


def load(path: Path | None = None) -> list[Remote]:
    path = path or config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e.strerror}")
    return parse(text, str(path))


def save(remotes: list[Remote], path: Path | None = None) -> Path:
    path = path or config_path()
    _check_unique(remotes, str(path))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(dumps(remotes), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        raise ConfigError(f"cannot write {path}: {e.strerror}")
    return path


def add_remote(name: str, agent: str, path: Path | None = None) -> Remote:
    remotes = load(path)
    new = _make_remote(name, agent, "remote")
    if any(r.name == new.name for r in remotes):
        raise ConfigError(f"remote '{new.name}' already exists", code=1)
    save(remotes + [new], path)
    return new


def remove_remote(name: str, path: Path | None = None) -> None:
    remotes = load(path)
    kept = [r for r in remotes if r.name != name]
    if len(kept) == len(remotes):
        raise ConfigError(f"no remote named '{name}'", code=2)
    save(kept, path)


def _make_remote(name, agent, where: str) -> Remote:
    for key, value in (("name", name), ("agent", agent)):
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{where}: '{key}' must be a non-empty string")
        if not NAME_RE.match(value):
            raise ConfigError(f"{where}: invalid {key} '{value}' (letters, digits, '_', '.', '-')")
    return Remote(name, agent)


def _check_unique(remotes: list[Remote], source: str) -> None:
    seen: set[str] = set()
    for r in remotes:
        if r.name in seen:
            raise ConfigError(f"{source}: duplicate remote name '{r.name}'")
        seen.add(r.name)


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _loads(text: str, source: str) -> dict:
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except _tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{source}: invalid TOML: {e}")
    return _loads_subset(text, source)


_TABLE_ARRAY = re.compile(r"^\[\[\s*([A-Za-z0-9_-]+)\s*\]\]$")
_KV = re.compile(r'^([A-Za-z0-9_-]+)\s*=\s*(".*"|\'.*\')$')


def _loads_subset(text: str, source: str) -> dict:
    """Fallback for Python 3.10: the TOML subset this file uses
    ([[array]] tables of string key/values, comments, blank lines)."""
    data: dict = {}
    current: dict | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        m = _TABLE_ARRAY.match(line)
        if m:
            current = {}
            data.setdefault(m.group(1), []).append(current)
            continue
        m = _KV.match(line)
        if not m:
            raise ConfigError(f"{source}: invalid TOML at line {lineno}")
        key, value = m.group(1), _unquote(m.group(2), source, lineno)
        target = current if current is not None else data
        if key in target:
            raise ConfigError(f"{source}: invalid TOML at line {lineno}: duplicate key '{key}'")
        target[key] = value
    return data


def _strip_comment(line: str) -> str:
    quote, escaped = None, False
    for i, ch in enumerate(line):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def _unquote(token: str, source: str, lineno: int) -> str:
    if token[0] == "'":
        return token[1:-1]
    body, out, i = token[1:-1], [], 0
    escapes = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 >= len(body) or body[i + 1] not in escapes:
                raise ConfigError(f"{source}: invalid TOML at line {lineno}: bad escape")
            out.append(escapes[body[i + 1]])
            i += 2
            continue
        if ch == '"':
            raise ConfigError(f"{source}: invalid TOML at line {lineno}")
        out.append(ch)
        i += 1
    return "".join(out)
