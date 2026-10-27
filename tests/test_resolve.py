import pytest

from hermes_hub import UsageError, config, discovery
from hermes_hub.resolve import Catalog, build_command

from conftest import PROFILE_LIST_OUTPUT, PROFILES


def runner_with(output, code=0):
    return lambda argv: (code, output)


def test_parse_real_profile_table():
    assert discovery.parse_profile_list(PROFILE_LIST_OUTPUT) == PROFILES


def test_parse_plain_list_and_ansi():
    out = "\x1b[1mdefault\x1b[0m\n* coach\nfinance\n"
    assert discovery.parse_profile_list(out) == ["default", "coach", "finance"]


def test_discovery_uses_hermes_profile_list(isolated):
    assert discovery.list_profiles() == PROFILES
    assert isolated == [["hermes", "profile", "list"]]


def test_discovery_falls_back_to_profiles_dir(tmp_path):
    home = tmp_path / "hh"
    for name in ("finance", "coach"):
        (home / "profiles" / name).mkdir(parents=True)
    (home / "profiles" / "notes.txt").write_text("not a profile")
    expected = ["default", "coach", "finance"]
    assert discovery.list_profiles(runner_with("", code=1), home) == expected
    assert discovery.list_profiles(runner_with("Error: no profiles?\n\n"), home) == expected

    def missing(argv):
        raise FileNotFoundError(argv[0])

    assert discovery.list_profiles(missing, home) == expected


def test_discovery_fallback_without_profiles_dir(tmp_path):
    assert discovery.list_profiles(runner_with("", 1), tmp_path / "none") == ["default"]


@pytest.fixture
def catalog(config_file):
    return Catalog.discover(runner_with(PROFILE_LIST_OUTPUT), config_file)


def test_local_interactive(catalog):
    assert build_command(catalog.resolve("coach")) == ["hermes", "-p", "coach", "chat"]


def test_local_oneshot(catalog):
    assert build_command(catalog.resolve("finance"), "saldo?") == [
        "hermes", "-p", "finance", "chat", "-q", "saldo?", "--oneshot", "-Q",
    ]


def test_remote_by_config_name(catalog):
    agent = catalog.resolve("vps")
    assert agent.kind == "remote"
    assert build_command(agent, "hola") == ["hermes", "peer", "dm", "vps/viaje", "hola"]
    assert build_command(agent) == ["hermes", "peer", "dm", "vps/viaje"]


def test_remote_explicit_peer_agent(catalog):
    assert build_command(catalog.resolve("spark/dev"), "x") == ["hermes", "peer", "dm", "spark/dev", "x"]


def test_dash_prompts_are_not_parsed_as_options(catalog):
    assert build_command(catalog.resolve("coach"), "-v?") == [
        "hermes", "-p", "coach", "chat", "--query=-v?", "--oneshot", "-Q",
    ]
    assert build_command(catalog.resolve("vps"), "-v?") == ["hermes", "peer", "dm", "vps/viaje", "--", "-v?"]


def test_unknown_profile_is_usage_error(catalog):
    with pytest.raises(UsageError) as e:
        catalog.resolve("nope")
    assert e.value.code == 2
    assert "unknown agent 'nope'" in str(e.value)
    assert "coach" in str(e.value) and "vps" in str(e.value)


@pytest.mark.parametrize("bad", ["", "a/", "/b", "a/b/c"])
def test_malformed_targets(catalog, bad):
    with pytest.raises(UsageError):
        catalog.resolve(bad)


def test_name_clash_between_local_and_remote_is_ambiguous(tmp_path):
    path = tmp_path / "c.toml"
    config.add_remote("coach", "viaje", path)
    cat = Catalog.discover(runner_with(PROFILE_LIST_OUTPUT), path)
    with pytest.raises(UsageError, match="coach/viaje"):
        cat.resolve("coach")
    assert cat.resolve("coach/viaje").kind == "remote"


def test_agents_lists_locals_then_remotes(catalog):
    names = [(a.name, a.kind) for a in catalog.agents()]
    assert names == [(p, "local") for p in PROFILES] + [("vps", "remote")]


def test_hermes_binary_override(catalog, monkeypatch):
    monkeypatch.setenv("HERMES_HUB_HERMES", "/opt/hermes")
    assert build_command(catalog.resolve("dev"))[0] == "/opt/hermes"
