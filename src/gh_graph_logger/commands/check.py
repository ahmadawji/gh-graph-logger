"""Handler for `ghlog check` subcommand."""

from __future__ import annotations

import argparse

from gh_graph_logger.config import ConfigError, load_config
from gh_graph_logger.console import format_status, safe_print
from gh_graph_logger.exitcodes import GUARD_FAILED, OK
from gh_graph_logger.guards import (
    GuardError,
    normalize_repo_url,
    require_git,
    require_git_repo,
    require_log_repo,
    require_remote_access,
)


def handle_check(arguments: argparse.Namespace) -> int:
    """Run all four guards and report verification status."""
    all_checks_passed = True

    # 1. require_git
    try:
        git_version = require_git()
        safe_print(f"{format_status(True)} Git executable ({git_version})")
    except GuardError as exception:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Git executable: {exception.message}")
        if exception.hint:
            safe_print(f"   Hint: {exception.hint}")

    # 2. require_git_repo
    try:
        current_work_repo = require_git_repo()
        safe_print(f"{format_status(True)} Inside git repository ({current_work_repo})")
    except GuardError as exception:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Inside git repository: {exception.message}")
        if exception.hint:
            safe_print(f"   Hint: {exception.hint}")

    # 3 & 4: Log repository clone and remote access
    try:
        loaded_configuration = load_config()
    except ConfigError as exception:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Log repository: configuration corrupt — {exception}")
        safe_print(
            f"{format_status(False)} Remote access: cannot verify due to corrupt configuration"
        )
        return GUARD_FAILED

    if loaded_configuration is None:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Log repository: not configured — run ghlog init")
        safe_print(f"{format_status(False)} Remote access: log repository not configured")
    else:
        try:
            log_repo_path = require_log_repo(loaded_configuration)
            safe_print(f"{format_status(True)} Log repository clone ({log_repo_path})")
        except GuardError as exception:
            all_checks_passed = False
            safe_print(f"{format_status(False)} Log repository: {exception.message}")
            if exception.hint:
                safe_print(f"   Hint: {exception.hint}")

        try:
            normalize_repo_url(loaded_configuration.log_repo_url)
            require_remote_access(loaded_configuration.log_repo_url)
            safe_print(f"{format_status(True)} Remote access ({loaded_configuration.log_repo_url})")
        except GuardError as exception:
            all_checks_passed = False
            safe_print(f"{format_status(False)} Remote access: {exception.message}")
            if exception.hint:
                safe_print(f"   Hint: {exception.hint}")

    return OK if all_checks_passed else GUARD_FAILED
