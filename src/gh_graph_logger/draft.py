"""Draft rendering, editor management, and comment stripping for gh-graph-logger."""

from __future__ import annotations

import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path

from gh_graph_logger.collector import CommitRecord
from gh_graph_logger.gitutil import GitError, run_git


def draft_path(repo_root: Path) -> Path:
    """Return the path to the draft markdown file in the repository's git directory.

    Queries `git rev-parse --absolute-git-dir` to ensure worktrees and submodules
    target the true git metadata directory rather than a file or worktree root.
    Creates the parent 'ghlog' directory if it does not already exist.

    Args:
        repo_root: Path to the working git repository root.

    Returns:
        The resolved Path to <git-dir>/ghlog/draft.md.
    """
    git_dir_string = run_git(["rev-parse", "--absolute-git-dir"], cwd=repo_root).strip()
    git_directory = Path(git_dir_string).resolve()
    ghlog_directory = git_directory / "ghlog"
    ghlog_directory.mkdir(parents=True, exist_ok=True)
    return ghlog_directory / "draft.md"


def render_draft(
    project: str,
    commits: list[CommitRecord],
    generated_at: datetime,
    include_body: bool = False,
) -> str:
    """Render draft markdown content containing commits and comment instructions.

    Format:
        ## <project> — <YYYY-MM-DD HH:MM>

        - HH:MM `<short_hash>` <subject>
          <body indented by 2 spaces if include_body=True and body non-empty>

        # Lines starting with '#' are comments and will be ignored.
        ...

    Note:
        The section heading starts with '##' and is strictly preserved during
        comment stripping. User instructions start with '# ' so that stripping
        safely removes instructions while leaving the '##' heading untouched.
    """
    heading_timestamp = generated_at.strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        f"## {project} — {heading_timestamp}",
        "",
    ]

    for commit in commits:
        commit_time = commit.authored_at.strftime("%H:%M")
        lines.append(f"- {commit_time} `{commit.short_hash}` {commit.subject}")
        if include_body and commit.body:
            for body_line in commit.body.splitlines():
                if body_line.strip():
                    lines.append(f"  {body_line}")
                else:
                    lines.append("")

    lines.append("")
    lines.append("# Lines starting with '#' are comments and will be ignored.")
    lines.append("# Review your commits above and remove anything confidential or sensitive.")
    lines.append("# The '##' heading above will be preserved.")
    lines.append("# An empty file or removing all commit bullets will discard the draft.")
    lines.append("")

    return "\n".join(lines)


def strip_comments(text: str) -> str:
    """Remove comment lines starting with '#' while preserving markdown headings.

    Rule:
        Removes ONLY lines whose first character is '#' AND second character is not '#'.
        Lines starting with '##' (like the draft heading) or '###' are kept.

    Returns:
        Cleaned text stripped of trailing whitespace.
    """
    retained_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") and not line.startswith("##"):
            continue
        retained_lines.append(line)
    return "\n".join(retained_lines).rstrip()


def has_commits(cleaned_text: str) -> bool:
    """Return True if at least one commit bullet line remains in cleaned draft."""
    for line in cleaned_text.splitlines():
        if line.strip().startswith("- "):
            return True
    return False


def resolve_editor_command(repo_root: Path) -> list[str]:
    """Resolve the git editor command from `git var GIT_EDITOR`.

    Args:
        repo_root: Path to the working git repository root.

    Returns:
        List of command tokens suitable for subprocess execution.

    Raises:
        GitError: If git var GIT_EDITOR fails or returns an empty command.
    """
    try:
        raw_editor = run_git(["var", "GIT_EDITOR"], cwd=repo_root).strip()
    except GitError as exception:
        raise GitError(
            f"Failed to resolve git editor: {exception.message}",
            command_args=["git", "var", "GIT_EDITOR"],
        ) from exception

    if not raw_editor:
        raise GitError(
            "No git editor configured. Please set 'git config --global core.editor <editor>'."
        )

    is_posix = os.name != "nt"
    tokens = shlex.split(raw_editor, posix=is_posix)

    if not is_posix:
        cleaned_tokens: list[str] = []
        for token in tokens:
            if (token.startswith('"') and token.endswith('"')) or (
                token.startswith("'") and token.endswith("'")
            ):
                token = token[1:-1]
            cleaned_tokens.append(token)
        tokens = cleaned_tokens

    if not tokens:
        raise GitError("Configured git editor command is empty.")

    return tokens


def open_editor(repo_root: Path, path: Path) -> None:
    """Open the draft file in the configured git editor.

    Executes the editor command with the draft path appended, inheriting the terminal.

    Args:
        repo_root: Root path of the working repository.
        path: Path to the draft markdown file.

    Raises:
        GitError: If the editor binary is missing or exits with a non-zero exit code.
    """
    command_tokens = resolve_editor_command(repo_root)
    full_command = [*command_tokens, str(path)]

    try:
        process = subprocess.run(full_command, shell=False)
    except FileNotFoundError as exception:
        raise GitError(
            f"Editor executable '{command_tokens[0]}' was not found on system PATH. "
            "Please configure a valid editor using 'git config --global core.editor <editor>' "
            "or set the GIT_EDITOR environment variable.",
            command_args=full_command,
        ) from exception
    except OSError as exception:
        raise GitError(
            f"Failed to launch editor '{full_command[0]}': {exception}",
            command_args=full_command,
        ) from exception

    if process.returncode != 0:
        raise GitError(
            f"Editor '{command_tokens[0]}' exited with non-zero exit code {process.returncode}.",
            command_args=full_command,
            returncode=process.returncode,
        )
