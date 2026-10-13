"""Tests for configuration persistence and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_graph_logger.config import (
    Config,
    ConfigError,
    _parse_simple_toml,
    config_dir,
    config_path,
    load_config,
    save_config,
)


def test_config_dir_and_path_env_var(ghlog_home: Path) -> None:
    """Config dir and config path respect GHLOG_HOME environment variable."""
    assert config_dir() == ghlog_home.resolve()
    assert config_path() == (ghlog_home / "config.toml").resolve()


def test_load_config_missing_file_returns_none(ghlog_home: Path) -> None:
    """load_config returns None when config.toml does not exist."""
    assert load_config() is None


def test_config_round_trip(ghlog_home: Path, tmp_path: Path) -> None:
    """Configuration saves and reloads correctly with all fields and special characters."""
    clone_directory = tmp_path / "clones" / "daily-log"
    configuration = Config(
        log_repo_url="https://github.com/example-user/daily-log.git",
        clone_path=str(clone_directory),
        branch="main",
        github_email="developer@example.com",
        last_push={
            "project-alpha": "2026-10-12T08:30:00Z",
            "project-beta": "2026-10-12T14:45:10Z",
        },
    )

    save_config(configuration)
    loaded_configuration = load_config()

    assert loaded_configuration is not None
    assert loaded_configuration.log_repo_url == configuration.log_repo_url
    assert loaded_configuration.clone_path == str(clone_directory.resolve())
    assert loaded_configuration.branch == "main"
    assert loaded_configuration.github_email == "developer@example.com"
    assert loaded_configuration.last_push == {
        "project-alpha": "2026-10-12T08:30:00Z",
        "project-beta": "2026-10-12T14:45:10Z",
    }


def test_config_directory_as_target_raises_error(ghlog_home: Path) -> None:
    """If config path exists as a directory, ConfigError is raised."""
    target_file = config_path()
    target_file.mkdir(parents=True)
    with pytest.raises(ConfigError, match="is a directory"):
        load_config()


@pytest.mark.parametrize(
    "corrupt_content",
    [
        "this is not toml at all !@#$",
        "log_repo_url = 123",
        (
            "log_repo_url = 'url'\nclone_path = 'path'\nbranch = 'main'\n"
            "github_email = 'e@mail'\nlast_push = 'not_a_table'"
        ),
        (
            "log_repo_url = 'url'\nclone_path = 'path'\nbranch = 'main'\n"
            "github_email = 'e@mail'\n[last_push]\nproj = 123"
        ),
    ],
)
def test_load_config_corrupt_content_raises_config_error(
    ghlog_home: Path, corrupt_content: str
) -> None:
    """Corrupt or invalid configuration files raise ConfigError."""
    target_file = config_path()
    target_file.write_text(corrupt_content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()


@pytest.mark.parametrize(
    "empty_field_toml",
    [
        'log_repo_url = ""\nclone_path = "p"\nbranch = "b"\ngithub_email = "e@mail"',
        'log_repo_url = "   "\nclone_path = "p"\nbranch = "b"\ngithub_email = "e@mail"',
        'log_repo_url = "u"\nclone_path = ""\nbranch = "b"\ngithub_email = "e@mail"',
        'log_repo_url = "u"\nclone_path = "p"\nbranch = "  "\ngithub_email = "e@mail"',
        'log_repo_url = "u"\nclone_path = "p"\nbranch = "b"\ngithub_email = ""',
    ],
)
def test_load_config_empty_required_field_raises_config_error(
    ghlog_home: Path, empty_field_toml: str
) -> None:
    """Empty or whitespace-only required fields raise ConfigError."""
    target_file = config_path()
    target_file.write_text(empty_field_toml, encoding="utf-8")
    with pytest.raises(ConfigError, match="has missing or empty required field"):
        load_config()


def test_parse_simple_toml_fallback_parser() -> None:
    """The built-in TOML parser correctly parses valid config subsets."""
    sample_toml = """
    # Sample comment
    log_repo_url = "https://github.com/test/repo.git"
    clone_path = 'C:\\logs\\repo'
    branch = "main"
    github_email = "test@example.com"

    [last_push]
    "project-a" = "2026-10-12T10:00:00Z"
    project-b = "2026-10-12T12:00:00Z"
    """
    parsed = _parse_simple_toml(sample_toml)
    assert parsed["log_repo_url"] == "https://github.com/test/repo.git"
    assert parsed["clone_path"] == "C:\\logs\\repo"
    assert parsed["branch"] == "main"
    assert parsed["github_email"] == "test@example.com"
    assert parsed["last_push"]["project-a"] == "2026-10-12T10:00:00Z"
    assert parsed["last_push"]["project-b"] == "2026-10-12T12:00:00Z"


def test_parse_simple_toml_syntax_errors() -> None:
    """The built-in TOML parser raises ConfigError on syntax errors."""
    with pytest.raises(ConfigError, match="missing '='"):
        _parse_simple_toml("just a bad line without equals")

    with pytest.raises(ConfigError, match="Empty section header"):
        _parse_simple_toml("[]")

    with pytest.raises(ConfigError, match="Unclosed string literal"):
        _parse_simple_toml('key = "unclosed')
