"""Tests for configuration persistence and validation using config.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gh_graph_logger.config import (
    Config,
    ConfigError,
    config_dir,
    config_path,
    load_config,
    save_config,
)


def test_config_dir_and_path_env_var(ghlog_home: Path) -> None:
    """Config dir and config path respect GHLOG_HOME environment variable."""
    assert config_dir() == ghlog_home.resolve()
    assert config_path() == (ghlog_home / "config.json").resolve()


def test_load_config_missing_file_returns_none(ghlog_home: Path) -> None:
    """load_config returns None when config.json does not exist."""
    assert load_config() is None


def test_config_round_trip(ghlog_home: Path, tmp_path: Path) -> None:
    """Configuration saves and reloads correctly with all fields."""
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
    with pytest.raises(ConfigError):
        load_config()


@pytest.mark.parametrize(
    "corrupt_content",
    [
        "this is not json at all !@#$",
        "12345",
        '{"log_repo_url": 123}',
        '{"clone_path": "/some/path"}',  # missing log_repo_url
        '{"log_repo_url": "", "clone_path": "/some/path"}',  # empty log_repo_url
        '{"log_repo_url": "https://github.com/u/r", "clone_path": ""}',  # empty clone_path
        '{"log_repo_url": "   ", "clone_path": "   "}',  # whitespace only
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


def test_save_config_creates_valid_json_file(ghlog_home: Path, tmp_path: Path) -> None:
    """save_config writes standard formatted JSON."""
    clone_dir = tmp_path / "clone"
    cfg = Config(
        log_repo_url="git@github.com:user/log.git",
        clone_path=str(clone_dir),
        branch="main",
        github_email="user@test.com",
        last_push={},
    )
    save_config(cfg)
    file_path = config_path()
    assert file_path.exists()
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data["log_repo_url"] == "git@github.com:user/log.git"
    assert data["clone_path"] == str(clone_dir.resolve())
    assert data["branch"] == "main"
    assert data["github_email"] == "user@test.com"
