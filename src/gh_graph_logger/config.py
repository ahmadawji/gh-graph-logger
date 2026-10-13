"""Configuration management for gh-graph-logger."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Exception raised when configuration is invalid or unreadable."""


@dataclass
class Config:
    """Global configuration settings for gh-graph-logger."""

    log_repo_url: str
    clone_path: str
    branch: str = "main"
    github_email: str = ""
    last_push: dict[str, str] = field(default_factory=dict)


def config_dir() -> Path:
    """Return the configuration directory path."""
    env_home = os.environ.get("GHLOG_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return (Path.home() / ".gh-graph-logger").resolve()


def config_path() -> Path:
    """Return the configuration file path."""
    return config_dir() / "config.json"


def load_config() -> Config | None:
    """Load configuration from config.json, or None if it doesn't exist."""
    path = config_path()
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Config(
            log_repo_url=data["log_repo_url"],
            clone_path=str(Path(data["clone_path"]).resolve()),
            branch=data.get("branch", "main"),
            github_email=data.get("github_email", ""),
            last_push=data.get("last_push", {}),
        )
    except (json.JSONDecodeError, KeyError, OSError, TypeError) as exc:
        raise ConfigError(f"Corrupt or invalid configuration file at '{path}': {exc}") from exc


def save_config(config: Config) -> None:
    """Save configuration to config.json atomically."""
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_file = tempfile.NamedTemporaryFile(
        "w",
        dir=target.parent,
        delete=False,
        encoding="utf-8",
    )
    temp_path = Path(temp_file.name)

    try:
        json.dump(asdict(config), temp_file, indent=2)
        temp_file.flush()
        temp_file.close()
        os.replace(temp_path, target)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise ConfigError(f"Failed to save configuration to '{target}': {exc}") from exc
