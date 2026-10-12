"""Configuration management for gh-graph-logger."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = None  # type: ignore[assignment]


class ConfigError(Exception):
    """Exception raised when configuration is invalid, corrupt, or unreadable."""


@dataclass
class Config:
    """Global configuration settings for gh-graph-logger."""

    log_repo_url: str
    clone_path: str
    branch: str
    github_email: str
    last_push: dict[str, str] = field(default_factory=dict)


def config_dir() -> Path:
    """Return the configuration directory path.

    Uses environment variable GHLOG_HOME if set, otherwise ~/.gh-graph-logger.
    """
    environment_home = os.environ.get("GHLOG_HOME")
    if environment_home:
        return Path(environment_home).expanduser().resolve()
    return (Path.home() / ".gh-graph-logger").resolve()


def config_path() -> Path:
    """Return the configuration file path."""
    return config_dir() / "config.toml"


def _parse_simple_toml(content: str) -> dict[str, Any]:
    """Parse a subset of TOML used by gh-graph-logger without external dependencies.

    Supports comments, section headers, and key-value string pairs.
    """
    parsed_data: dict[str, Any] = {}
    current_section: str | None = None

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue

        if stripped_line.startswith("[") and stripped_line.endswith("]"):
            section_name = stripped_line[1:-1].strip()
            if not section_name:
                raise ConfigError(f"Empty section header at line {line_number}")
            current_section = section_name
            if current_section not in parsed_data:
                parsed_data[current_section] = {}
            elif not isinstance(parsed_data[current_section], dict):
                raise ConfigError(
                    f"Duplicate or invalid section '{current_section}' at line {line_number}"
                )
            continue

        if "=" not in stripped_line:
            raise ConfigError(f"Invalid syntax (missing '=') at line {line_number}: {raw_line}")

        raw_key, raw_value = stripped_line.split("=", 1)
        key = raw_key.strip()
        value = raw_value.strip()

        if (key.startswith('"') and key.endswith('"')) or (
            key.startswith("'") and key.endswith("'")
        ):
            try:
                key = json.loads(key) if key.startswith('"') else key[1:-1]
            except Exception as exception:
                raise ConfigError(
                    f"Invalid key quoting at line {line_number}: {raw_key}"
                ) from exception

        if not key:
            raise ConfigError(f"Empty key name at line {line_number}")

        if value.startswith('"'):
            if not value.endswith('"') or len(value) < 2:
                raise ConfigError(f"Unclosed string literal at line {line_number}: {raw_value}")
            try:
                parsed_value = json.loads(value)
            except Exception as exception:
                raise ConfigError(
                    f"Invalid string escape at line {line_number}: {raw_value}"
                ) from exception
        elif value.startswith("'"):
            if not value.endswith("'") or len(value) < 2:
                raise ConfigError(
                    f"Unclosed single-quoted string at line {line_number}: {raw_value}"
                )
            parsed_value = value[1:-1]
        else:
            raise ConfigError(f"Unsupported or unquoted value at line {line_number}: {raw_value}")

        if current_section is None:
            parsed_data[key] = parsed_value
        else:
            if not isinstance(parsed_data[current_section], dict):
                raise ConfigError(f"Section '{current_section}' is not a dictionary")
            parsed_data[current_section][key] = parsed_value

    return parsed_data


def load_config() -> Config | None:
    """Load configuration from config.toml.

    Returns:
        Config instance if configuration exists, or None if the file is missing.

    Raises:
        ConfigError: If configuration file is corrupt, unreadable, or missing fields.
    """
    file_path = config_path()
    if not file_path.exists():
        return None

    if file_path.is_dir():
        raise ConfigError(f"Configuration path '{file_path}' is a directory, not a file.")

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exception:
        raise ConfigError(
            f"Failed to read configuration file '{file_path}': {exception}"
        ) from exception

    try:
        if tomllib is not None:
            data = tomllib.loads(content)
        else:
            data = _parse_simple_toml(content)
    except Exception as exception:
        raise ConfigError(f"Corrupt configuration file '{file_path}': {exception}") from exception

    required_fields = ["log_repo_url", "clone_path", "branch", "github_email"]
    for field_name in required_fields:
        if field_name not in data or not isinstance(data[field_name], str):
            raise ConfigError(
                f"Configuration file '{file_path}' is missing required string field '{field_name}'."
            )

    last_push_data = data.get("last_push", {})
    if not isinstance(last_push_data, dict):
        raise ConfigError(
            f"Configuration file '{file_path}' contains invalid 'last_push' table "
            "(expected dictionary)."
        )

    for project_name, timestamp in last_push_data.items():
        if not isinstance(project_name, str) or not isinstance(timestamp, str):
            raise ConfigError(
                f"Configuration file '{file_path}' contains invalid 'last_push' entry: "
                f"{project_name}={timestamp}"
            )

    return Config(
        log_repo_url=data["log_repo_url"],
        clone_path=str(Path(data["clone_path"]).resolve()),
        branch=data["branch"],
        github_email=data["github_email"],
        last_push=dict(last_push_data),
    )


def save_config(config: Config) -> None:
    """Save configuration to config.toml atomically.

    Writes to a temporary file in the configuration directory and replaces the target.

    Raises:
        ConfigError: If writing or replacing fails.
    """
    target_path = config_path()
    parent_directory = target_path.parent
    parent_directory.mkdir(parents=True, exist_ok=True)

    absolute_clone_path = str(Path(config.clone_path).resolve())

    lines: list[str] = [
        "# Configuration for gh-graph-logger",
        f"log_repo_url = {json.dumps(config.log_repo_url)}",
        f"clone_path = {json.dumps(absolute_clone_path)}",
        f"branch = {json.dumps(config.branch)}",
        f"github_email = {json.dumps(config.github_email)}",
    ]

    if config.last_push:
        lines.append("")
        lines.append("[last_push]")
        for project_name, timestamp in sorted(config.last_push.items()):
            lines.append(f"{json.dumps(project_name)} = {json.dumps(timestamp)}")

    lines.append("")
    serialized_content = "\n".join(lines)

    temporary_file = tempfile.NamedTemporaryFile(
        "w",
        dir=parent_directory,
        delete=False,
        encoding="utf-8",
    )
    temporary_file_path = Path(temporary_file.name)

    try:
        temporary_file.write(serialized_content)
        temporary_file.flush()
        temporary_file.close()
        os.replace(temporary_file_path, target_path)
    except Exception as exception:
        if temporary_file_path.exists():
            temporary_file_path.unlink(missing_ok=True)
        raise ConfigError(
            f"Failed to save configuration to '{target_path}': {exception}"
        ) from exception
