"""Subcommand handlers for gh-graph-logger CLI."""

from __future__ import annotations

from gh_graph_logger.commands.check import handle_check
from gh_graph_logger.commands.collect import handle_collect
from gh_graph_logger.commands.config import handle_config
from gh_graph_logger.commands.init import handle_init

__all__ = [
    "handle_check",
    "handle_collect",
    "handle_config",
    "handle_init",
]
