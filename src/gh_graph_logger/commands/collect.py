"""Handler for `ghlog collect` subcommand."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from gh_graph_logger import draft
from gh_graph_logger.collector import (
    collect_commits,
    compute_window_start,
    parse_since,
    resolve_author_emails,
)
from gh_graph_logger.config import load_config
from gh_graph_logger.console import prompt, safe_print
from gh_graph_logger.exitcodes import ABORTED, ERROR, OK
from gh_graph_logger.guards import (
    GuardError,
    require_git,
    require_git_repo,
    require_log_repo,
)
from gh_graph_logger.project import resolve_project_name


def handle_collect(arguments: argparse.Namespace) -> int:
    """Collect commits from current repository and open a draft in git editor."""
    require_git()
    repo_root = require_git_repo()

    loaded_configuration = load_config()
    if loaded_configuration is None:
        raise GuardError(
            "gh-graph-logger is not configured.",
            hint="Run 'ghlog init' to configure your log repository.",
        )

    require_log_repo(loaded_configuration)

    since_override: datetime | None = None
    if arguments.since:
        try:
            since_override = parse_since(arguments.since)
        except ValueError as exception:
            safe_print(f"Error: {exception}", file=sys.stderr)
            return ERROR

    project_name = resolve_project_name(repo_root, override=arguments.project)
    now = datetime.now().astimezone()
    window_start = compute_window_start(
        project=project_name,
        last_push=loaded_configuration.last_push,
        now=now,
        since_override=since_override,
    )
    author_emails = resolve_author_emails(repo_root, override=arguments.author)

    target_draft_path = draft.draft_path(repo_root)
    reopen_existing_draft = False

    if target_draft_path.exists() and target_draft_path.stat().st_size > 0:
        existing_draft_text = target_draft_path.read_text(encoding="utf-8")
        existing_commits_count = draft.count_commit_lines(existing_draft_text)
        while True:
            choice = prompt(
                f"A draft already exists ({existing_commits_count} commits). "
                "[R]eopen it / [O]verwrite with fresh commits / [C]ancel",
                default="R",
            ).strip().lower()
            if choice in ("r", "reopen", ""):
                reopen_existing_draft = True
                updated_draft_text = draft.reappend_instructions_if_missing(existing_draft_text)
                target_draft_path.write_text(updated_draft_text, encoding="utf-8", newline="\n")
                break
            if choice in ("o", "overwrite"):
                reopen_existing_draft = False
                break
            if choice in ("c", "cancel"):
                safe_print("Aborted by user.")
                return ABORTED
            safe_print("Please enter 'r' to reopen, 'o' to overwrite, or 'c' to cancel.")

    if not reopen_existing_draft:
        commits = collect_commits(
            repo_root=repo_root,
            since=window_start,
            until=now,
            author_emails=author_emails,
            include_body=arguments.full,
        )
        if not commits:
            authors_display = ", ".join(author_emails)
            safe_print(
                f"No commits found since {window_start} for {authors_display}. "
                "Nothing to log."
            )
            return OK

        rendered_draft = draft.render_draft(
            project=project_name,
            commits=commits,
            generated_at=now,
            include_body=arguments.full,
        )
        target_draft_path.write_text(rendered_draft, encoding="utf-8", newline="\n")

    draft.open_editor(repo_root, target_draft_path)

    edited_content = target_draft_path.read_text(encoding="utf-8")
    cleaned_content = draft.strip_comments(edited_content)

    if not draft.has_commits(cleaned_content):
        target_draft_path.unlink(missing_ok=True)
        safe_print("Nothing to log - draft discarded.")
        return ABORTED

    target_draft_path.write_text(cleaned_content + "\n", encoding="utf-8", newline="\n")
    saved_commits_count = draft.count_commit_lines(cleaned_content)
    safe_print(
        f"Draft saved to {target_draft_path} with {saved_commits_count} commits. "
        "Publishing arrives in the next phase."
    )
    return OK
