"""Command line interface for gh-graph-logger."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from gh_graph_logger import __version__

# Exit code constants
OK: int = 0
ERROR: int = 1
GUARD_FAILED: int = 2
ABORTED: int = 3


def _stub(args: argparse.Namespace) -> int:
    """Stub handler for unreleased subcommands."""
    print("not implemented yet")
    return ERROR


def build_parser() -> argparse.ArgumentParser:
    """Build and configure the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ghlog",
        description="Log your daily commits to a private GitHub repo.",
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
    parser_init.add_argument("--root", type=str, help="Root directory for the log repo")
    parser_init.add_argument("--path", type=str, help="Path to an existing log repo clone")
    parser_init.add_argument(
        "--reclone", action="store_true", help="Re-clone the log repo from scratch"
    )
    parser_init.set_defaults(func=_stub)

    # check
    parser_check = subparsers.add_parser(
        "check",
        help="Verify environment, git repo, and remote access.",
    )
    parser_check.set_defaults(func=_stub)

    # collect
    parser_collect = subparsers.add_parser(
        "collect",
        help="Collect commits and create a draft.",
    )
    parser_collect.add_argument("--since", type=str, help="Collect commits since date/time")
    parser_collect.add_argument("--author", type=str, help="Author email(s) to filter by")
    parser_collect.add_argument(
        "--full", action="store_true", help="Include full commit messages"
    )
    parser_collect.add_argument("--project", type=str, help="Project name override")
    parser_collect.set_defaults(func=_stub)

    # push
    parser_push = subparsers.add_parser(
        "push",
        help="Push draft to the log repo.",
    )
    parser_push.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt"
    )
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
    parser_config.add_argument(
        "--show", action="store_true", help="Show current configuration"
    )
    parser_config.set_defaults(func=_stub)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the CLI. Returns exit code integer."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand is None:
        parser.print_help()
        return ERROR

    func = getattr(args, "func", None)
    if func is not None:
        return func(args)

    return ERROR


if __name__ == "__main__":
    sys.exit(main())
