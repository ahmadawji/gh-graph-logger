"""Handler for `ghlog config` subcommand."""

from __future__ import annotations

import argparse
import sys

from gh_graph_logger.config import ConfigError, config_path, load_config
from gh_graph_logger.console import safe_print
from gh_graph_logger.exitcodes import ERROR, OK


def handle_config(arguments: argparse.Namespace) -> int:
    """Display or manage configuration settings."""
    if not arguments.show:
        safe_print("Use 'ghlog config --show' to view configuration.", file=sys.stderr)
        return ERROR

    target_config_path = config_path()
    try:
        loaded_configuration = load_config()
    except ConfigError as exception:
        safe_print(f"Error reading configuration: {exception}", file=sys.stderr)
        return ERROR

    if loaded_configuration is None:
        safe_print(
            f"No configuration file found at '{target_config_path}'. Run `ghlog init`.",
            file=sys.stderr,
        )
        return ERROR

    safe_print(f"Configuration file: {target_config_path}")
    safe_print(f"  log_repo_url: {loaded_configuration.log_repo_url}")
    safe_print(f"  clone_path:   {loaded_configuration.clone_path}")
    safe_print(f"  branch:       {loaded_configuration.branch}")
    safe_print(f"  github_email: {loaded_configuration.github_email}")
    if loaded_configuration.last_push:
        safe_print("  last_push:")
        for project_name, timestamp in sorted(loaded_configuration.last_push.items()):
            safe_print(f"    {project_name}: {timestamp}")
    else:
        safe_print("  last_push:    (none)")

    return OK
