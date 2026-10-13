"""Unit tests for draft rendering, comment stripping, and editor interaction."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gh_graph_logger.collector import CommitRecord
from gh_graph_logger.draft import (
    draft_path,
    has_commits,
    open_editor,
    render_draft,
    resolve_editor_command,
    strip_comments,
)
from gh_graph_logger.gitutil import GitError, run_git


def test_render_draft_without_and_with_body() -> None:
    """render_draft formats header, bullets, optional body indent, and instructions."""
    now = datetime(2026, 10, 13, 14, 30, tzinfo=timezone.utc)
    commit = CommitRecord(
        full_hash="0123456789abcdef0123456789abcdef01234567",
        short_hash="0123456",
        authored_at=datetime(2026, 10, 13, 14, 25, tzinfo=timezone.utc),
        subject="Add awesome feature",
        body="Detailed description\nacross two lines",
    )

    # Without body
    draft_no_body = render_draft("my-project", [commit], generated_at=now, include_body=False)
    assert "## my-project — 2026-10-13 14:30" in draft_no_body
    assert "- 14:25 `0123456` Add awesome feature" in draft_no_body
    assert "Detailed description" not in draft_no_body
    assert "# Lines starting with '#' are comments" in draft_no_body

    # With body
    draft_with_body = render_draft("my-project", [commit], generated_at=now, include_body=True)
    assert "- 14:25 `0123456` Add awesome feature" in draft_with_body
    assert "  Detailed description" in draft_with_body
    assert "  across two lines" in draft_with_body


def test_strip_comments_rule() -> None:
    """strip_comments strips lines starting with '#' but keeps '##' and '###' headings."""
    sample_text = (
        "## my-project — 2026-10-13 14:30\n"
        "\n"
        "- 14:25 `0123456` Commit one\n"
        "- 14:28 `abcdef0` Commit two\n"
        "\n"
        "# Single comment line\n"
        "# Another comment\n"
        "### Retained subheading\n"
        "#\n"
        "  # Indented not starting with hash directly\n"
    )

    cleaned = strip_comments(sample_text)
    assert "## my-project — 2026-10-13 14:30" in cleaned
    assert "- 14:25 `0123456` Commit one" in cleaned
    assert "- 14:28 `abcdef0` Commit two" in cleaned
    assert "### Retained subheading" in cleaned
    assert "Single comment line" not in cleaned
    assert "Another comment" not in cleaned


def test_has_commits() -> None:
    """has_commits returns True if and only if at least one commit bullet remains."""
    assert has_commits("- 14:25 `0123456` Commit subject") is True
    assert has_commits("  - 14:25 `0123456` Indented bullet") is True
    assert has_commits("## my-project — 2026-10-13 14:30\n\nNo bullets here") is False
    assert has_commits("") is False


def test_draft_path_normal_repo_and_worktree(git_repo: Path, tmp_path: Path) -> None:
    """draft_path resolves to <git-dir>/ghlog/draft.md in normal repos and worktrees."""
    # 1. Normal repository
    path_normal = draft_path(git_repo)
    expected_git_dir = (git_repo / ".git").resolve()
    assert path_normal == expected_git_dir / "ghlog" / "draft.md"
    assert path_normal.parent.is_dir()

    # 2. Git worktree
    worktree_path = tmp_path / "worktree_dir"
    run_git(["worktree", "add", "-b", "worktree-branch", str(worktree_path)], cwd=git_repo)

    path_worktree = draft_path(worktree_path)
    # The draft file in a worktree must reside in the actual gitdir, NOT inside a .git file
    assert path_worktree.name == "draft.md"
    assert path_worktree.parent.name == "ghlog"
    assert path_worktree.parent.is_dir()
    # In a worktree, worktree_path / ".git" is a file, not a directory
    assert (worktree_path / ".git").is_file()
    # The draft path parent is a real directory inside the main repo's .git/worktrees
    assert path_worktree.parent != worktree_path / ".git" / "ghlog"


def test_resolve_editor_command_and_quotes(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """resolve_editor_command parses command strings and handles quotes properly."""
    # Simple editor
    run_git(["config", "core.editor", "nano"], cwd=git_repo)
    assert resolve_editor_command(git_repo) == ["nano"]

    # Quoted path with spaces
    quoted_editor = '"C:/Program Files/Editor/editor.exe" --wait'
    run_git(["config", "core.editor", quoted_editor], cwd=git_repo)
    parsed = resolve_editor_command(git_repo)
    assert parsed == ["C:/Program Files/Editor/editor.exe", "--wait"]


def test_open_editor_missing_binary_raises_git_error(
    git_repo: Path, tmp_path: Path
) -> None:
    """open_editor raises GitError with helpful hint when editor executable does not exist."""
    run_git(["config", "core.editor", "nonexistent-editor-binary-xyz"], cwd=git_repo)
    dummy_draft = tmp_path / "dummy.md"
    dummy_draft.write_text("dummy", encoding="utf-8")

    with pytest.raises(GitError, match="core.editor"):
        open_editor(git_repo, dummy_draft)
