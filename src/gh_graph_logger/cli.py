"""Command line interface for gh-graph-logger."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from gh_graph_logger import __version__
from gh_graph_logger.commands import (
    handle_check,
    handle_collect,
    handle_config,
    handle_init,
)
from gh_graph_logger.commands.init import _configure_clone_identity, repo_name_from_url
from gh_graph_logger.config import ConfigError
from gh_graph_logger.console import format_status, prompt, safe_print
from gh_graph_logger.exitcodes import ABORTED, ERROR, GUARD_FAILED, OK
from gh_graph_logger.gitutil import GitError
from gh_graph_logger.guards import GuardError

__all__ = [
    "ABORTED",
    "ERROR",
    "GUARD_FAILED",
    "OK",
    "_configure_clone_identity",
    "build_parser",
    "format_status",
    "handle_check",
    "handle_collect",
    "handle_config",
    "handle_init",
    "main",
    "prompt",
    "repo_name_from_url",
    "safe_print",
]


def _stub(arguments: argparse.Namespace) -> int:
    """Stub handler for unreleased subcommands."""
    safe_print("not implemented yet")
    return ERROR


def build_parser() -> argparse.ArgumentParser:
    """Build and configure the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ghlog",
        description=(
            "Log your daily commits to your GitHub log repository to keep your "
            "contribution graph active."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="subcommand",
        title="subcommands",
        description="available commands",
    )

    # init
    parser_init = subparsers.add_parser(
        "init",
        help="Initialize or configure the log repo clone.",
    )
    root_group = parser_init.add_mutually_exclusive_group()
    root_group.add_argument("--root", type=str, help="Root directory for the log repo")
    root_group.add_argument("--path", type=str, help="Path to an existing log repo clone")
    parser_init.add_argument("--url", type=str, help="Git URL of the log repository")
    parser_init.add_argument("--email", type=str, help="GitHub email for log commits")
    parser_init.add_argument(
        "--branch",
        type=str,
        help="Branch name in the log repo (default: remote default or main)",
    )
    parser_init.add_argument("--name", type=str, help="Git user name for log commits")
    parser_init.add_argument(
        "--yes",
        action="store_true",
        help="Accept defaults and auto-create missing root directory",
    )
    parser_init.set_defaults(func=handle_init)

    # check
    parser_check = subparsers.add_parser(
        "check",
        help="Verify environment, git repo, and remote access.",
    )
    parser_check.set_defaults(func=handle_check)

    # collect
    parser_collect = subparsers.add_parser(
        "collect",
        help="Collect commits and create a draft.",
    )
    parser_collect.add_argument("--since", type=str, help="Collect commits since date/time")
    parser_collect.add_argument("--author", type=str, help="Author email(s) to filter by")
    parser_collect.add_argument("--full", action="store_true", help="Include full commit messages")
    parser_collect.add_argument("--project", type=str, help="Project name override")
    parser_collect.set_defaults(func=handle_collect)

    # push
    parser_push = subparsers.add_parser(
        "push",
        help="Push draft to the log repo.",
    )
    parser_push.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser_push.set_defaults(func=_stub)

    # discard
    parser_discard = subparsers.add_parser(
        "discard",
        help="Discard current draft.",
    )
    parser_discard.set_defaults(func=_stub)

    # config
    parser_config = subparsers.add_parser(
        "config",
        help="View or manage configuration.",
    )
    parser_config.add_argument("--show", action="store_true", help="Show current configuration")
    parser_config.set_defaults(func=handle_config)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the CLI. Returns exit code integer."""
    try:
        parser = build_parser()
        arguments = parser.parse_args(argv)

        if arguments.subcommand is None:
            parser.print_help()
            return ERROR

        handler = getattr(arguments, "func", None)
        if handler is not None:
            return handler(arguments)

        return ERROR
    except KeyboardInterrupt:
        safe_print("\nAborted by user.", file=sys.stderr)
        return ABORTED
    except GuardError as exception:
        error_message = f"Error: {exception.message}"
        if exception.hint:
            error_message += f"\nHint: {exception.hint}"
        safe_print(error_message, file=sys.stderr)
        return GUARD_FAILED
    except (ConfigError, GitError) as exception:
        safe_print(f"Error: {exception}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
