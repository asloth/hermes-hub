import pytest

from hermes_hub import config
from hermes_hub.config import ConfigError, Remote

from conftest import CONFIG_TOML


def test_parse_spec_example():
    assert config.parse(CONFIG_TOML) == [Remote("vps", "viaje")]
    assert config.parse(CONFIG_TOML)[0].target == "vps/viaje"


def test_round_trip(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    remotes = [Remote("vps", "viaje"), Remote("spark", "dev")]
    config.save(remotes, path)
    assert config.load(path) == remotes
    assert config.parse(config.dumps(remotes)) == remotes


def test_missing_file_means_no_remotes(tmp_path):
    assert config.load(tmp_path / "nope.toml") == []


def test_empty_file_means_no_remotes(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("# nothing yet\n")
    assert config.load(path) == []


def test_duplicate_remote_names_rejected():
    text = CONFIG_TOML + '\n[[remote]]\nname = "vps"\nagent = "coach"\n'
    with pytest.raises(ConfigError, match="duplicate remote name 'vps'"):
        config.parse(text)


def test_save_rejects_duplicates(tmp_path):
    with pytest.raises(ConfigError, match="duplicate"):
        config.save([Remote("vps", "a"), Remote("vps", "b")], tmp_path / "c.toml")


def test_add_remote_rejects_duplicate(tmp_path):
    path = tmp_path / "config.toml"
    config.add_remote("vps", "viaje", path)
    with pytest.raises(ConfigError, match="already exists"):
        config.add_remote("vps", "coach", path)
    assert config.load(path) == [Remote("vps", "viaje")]


def test_add_and_remove(tmp_path):
    path = tmp_path / "config.toml"
    config.add_remote("vps", "viaje", path)
    config.add_remote("spark", "dev", path)
    config.remove_remote("vps", path)
    assert config.load(path) == [Remote("spark", "dev")]
    with pytest.raises(ConfigError) as e:
        config.remove_remote("vps", path)
    assert e.value.code == 2


@pytest.mark.parametrize("key", ["url", "key", "token"])
def test_credentials_and_urls_not_accepted(key):
    with pytest.raises(ConfigError, match="unsupported key"):
        config.parse(f'[[remote]]\nname = "vps"\nagent = "viaje"\n{key} = "x"\n')


@pytest.mark.parametrize(
    "text",
    [
        '[[remote]]\nagent = "viaje"\n',  # missing name
        '[[remote]]\nname = "vps"\n',  # missing agent
        '[[remote]]\nname = "a/b"\nagent = "viaje"\n',  # slash would break peer/agent
        '[[remote]]\nname = "vps"\nagent = 3\n',  # not a string
        "[[remote]\nname = ",  # not TOML
    ],
)
def test_invalid_config(text):
    with pytest.raises(ConfigError):
        config.parse(text)


def test_python310_fallback_parser(monkeypatch):
    """Same results without tomllib (Python 3.10)."""
    monkeypatch.setattr(config, "_tomllib", None)
    assert config.parse(CONFIG_TOML) == [Remote("vps", "viaje")]
    remotes = [Remote("vps", "viaje"), Remote("spark", "dev")]
    assert config.parse(config.dumps(remotes)) == remotes
    with pytest.raises(ConfigError, match="duplicate"):
        config.parse(CONFIG_TOML * 2)
    with pytest.raises(ConfigError):
        config.parse("[[remote]\n")
