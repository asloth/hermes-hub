"""Turn a target name into the exact hermes argv. Shared by the CLI and the MCP server.

Targets:
  <profile>          a local profile             -> hermes -p <profile> chat [...]
  <remote>           a remote from config.toml   -> hermes peer dm <remote>/<agent> [...]
  <peer>/<agent>     explicit remote form        -> hermes peer dm <peer>/<agent> [...]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hermes_hub import UsageError, config, discovery


@dataclass(frozen=True)
class Agent:
    kind: str  # "local" or "remote"
    name: str  # what the user types / picks
    profile: str = ""  # local only
    peer: str = ""  # remote only
    agent: str = ""  # remote only

    @property
    def peer_target(self) -> str:
        return f"{self.peer}/{self.agent}"

    def describe(self) -> str:
        return "local profile" if self.kind == "local" else f"remote via hermes peer -> {self.peer_target}"

    def to_dict(self) -> dict:
        d = {"name": self.name, "kind": self.kind}
        if self.kind == "local":
            d["profile"] = self.profile
        else:
            d.update(peer=self.peer, agent=self.agent)
        return d


@dataclass
class Catalog:
    profiles: list[str]
    remotes: list[config.Remote]

    @classmethod
    def discover(cls, runner: discovery.Runner | None = None, config_file: Path | None = None) -> "Catalog":
        return cls(discovery.list_profiles(runner), config.load(config_file))

    def agents(self) -> list[Agent]:
        out = [Agent("local", p, profile=p) for p in self.profiles]
        out += [Agent("remote", r.name, peer=r.name, agent=r.agent) for r in self.remotes]
        return out

    def resolve(self, target: str) -> Agent:
        target = (target or "").strip()
        if not target:
            raise UsageError("empty target")
        if "/" in target:
            peer, _, agent = target.partition("/")
            if not (config.NAME_RE.match(peer) and config.NAME_RE.match(agent)):
                raise UsageError(f"invalid remote target '{target}' (expected <peer>/<agent>)")
            return Agent("remote", target, peer=peer, agent=agent)
        local = target in self.profiles
        remote = next((r for r in self.remotes if r.name == target), None)
        if local and remote:
            raise UsageError(
                f"'{target}' is both a local profile and a remote; use '{remote.target}' for the remote"
            )
        if local:
            return Agent("local", target, profile=target)
        if remote:
            return Agent("remote", remote.name, peer=remote.name, agent=remote.agent)
        known = ", ".join(a.name for a in self.agents()) or "none"
        raise UsageError(f"unknown agent '{target}' (known: {known})")


def build_command(agent: Agent, prompt: str | None = None) -> list[str]:
    """Exact argv for talking to `agent`.

    Local, no prompt:  hermes -p <profile> chat
    Local, prompt:     hermes -p <profile> chat -q <prompt> --oneshot -Q  (only the reply)
    Remote, prompt:    hermes peer dm <peer>/<agent> <prompt>
    Remote, no prompt: hermes peer dm <peer>/<agent>   (hermes reads the message from stdin)

    A prompt starting with '-' would be parsed by hermes as an option, so it is
    passed as --query=<prompt> (local) or after '--' (remote).
    """
    hermes = discovery.hermes_bin()
    if agent.kind == "local":
        argv = [hermes, "-p", agent.profile, "chat"]
        if prompt is not None:
            query = [f"--query={prompt}"] if prompt.startswith("-") else ["-q", prompt]
            argv += query + ["--oneshot", "-Q"]
        return argv
    argv = [hermes, "peer", "dm", agent.peer_target]
    if prompt is not None:
        argv += ["--", prompt] if prompt.startswith("-") else [prompt]
    return argv
