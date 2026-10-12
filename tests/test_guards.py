"""Tests for environment and repository guard checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_graph_logger.config import Config
from gh_graph_logger.gitutil import GitNotFoundError, run_git
from gh_graph_logger.guards import (
    GuardError,
    normalize_repo_url,
    require_git,
    require_git_repo,
    require_log_repo,
    require_remote_access,
)


def test_normalize_repo_url() -> None:
    """normalize_repo_url standardizes URLs, trailing slashes, .git, and SSH/HTTPS."""
    assert normalize_repo_url("https://github.com/org/repo.git") == "https://github.com/org/repo"
    assert normalize_repo_url("https://github.com/org/repo.git/") == "https://github.com/org/repo"
    assert normalize_repo_url("https://github.com/org/repo/") == "https://github.com/org/repo"
    assert normalize_repo_url("file:///c:/logs/repo.git") == "c:/logs/repo"
    assert normalize_repo_url("file:///C:/logs/repo.git") == "c:/logs/repo"
    assert normalize_repo_url("C:\\logs\\repo.git\\") == "c:/logs/repo"
    assert normalize_repo_url("D:\\Logs\\MyRepo.git\\") == "d:/Logs/MyRepo"
    assert normalize_repo_url("/var/Logs/MyRepo.git/") == "/var/Logs/MyRepo"

    # GitHub SSH vs HTTPS equivalence (case-insensitive)
    ssh_url = "git@github.com:MyOrg/MyRepo.git"
    https_url = "https://github.com/myorg/myrepo"
    assert normalize_repo_url(ssh_url) == normalize_repo_url(https_url)
    assert normalize_repo_url("ssh://git@github.com/MyOrg/MyRepo") == normalize_repo_url(https_url)

    # Hyphen injection rejection
    with pytest.raises(GuardError, match="URLs starting with '-' are not permitted"):
        normalize_repo_url("--upload-pack=calc.exe")


def test_require_git_success() -> None:
    """require_git returns the git version string."""
    version = require_git()
    assert version.startswith("git version")


def test_require_git_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_git raises GuardError when git binary is missing."""

    def mock_run_git(*args: object, **kwargs: object) -> str:
        raise GitNotFoundError("git not found")

    monkeypatch.setattr("gh_graph_logger.guards.run_git", mock_run_git)

    with pytest.raises(GuardError, match="git executable not found") as exc_info:
        require_git()
    assert "Install git" in exc_info.value.hint


def test_require_git_repo_inside(git_repo: Path) -> None:
    """require_git_repo returns repository root when inside a git repository."""
    toplevel = require_git_repo(cwd=git_repo)
    assert toplevel == git_repo.resolve()

    subfolder = git_repo / "sub" / "folder"
    subfolder.mkdir(parents=True)
    assert require_git_repo(cwd=subfolder) == git_repo.resolve()


def test_require_git_repo_outside(tmp_path: Path) -> None:
    """require_git_repo raises GuardError when outside a git repository."""
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    with pytest.raises(GuardError, match="Not inside a git repository") as exc_info:
        require_git_repo(cwd=non_repo)
    assert "git work repository" in exc_info.value.hint


def test_require_log_repo_missing_path(tmp_path: Path) -> None:
    """require_log_repo raises GuardError when clone directory is missing."""
    missing_path = tmp_path / "missing_clone"
    config = Config(
        log_repo_url="https://github.com/user/logs.git",
        clone_path=str(missing_path),
        branch="main",
        github_email="user@example.com",
    )
    with pytest.raises(GuardError, match="Log repo not found at") as exc_info:
        require_log_repo(config)
    assert "ghlog init --path" in exc_info.value.hint


def test_require_log_repo_not_a_git_repo(tmp_path: Path) -> None:
    """require_log_repo raises GuardError when path is not a git repository."""
    not_repo_dir = tmp_path / "not_git"
    not_repo_dir.mkdir()
    config = Config(
        log_repo_url="https://github.com/user/logs.git",
        clone_path=str(not_repo_dir),
        branch="main",
        github_email="user@example.com",
    )
    with pytest.raises(GuardError, match="is not a git repository") as exc_info:
        require_log_repo(config)
    assert "ghlog init --path" in exc_info.value.hint


def test_require_log_repo_not_toplevel(git_repo: Path) -> None:
    """require_log_repo raises GuardError when clone path is a subdirectory of a repo."""
    subdir = git_repo / "child_directory"
    subdir.mkdir()
    config = Config(
        log_repo_url="https://github.com/user/logs.git",
        clone_path=str(subdir),
        branch="main",
        github_email="user@example.com",
    )
    with pytest.raises(GuardError, match="is not the root of a git repository") as exc_info:
        require_log_repo(config)
    assert "ghlog init --path" in exc_info.value.hint


def test_require_log_repo_origin_url_mismatch(git_repo: Path) -> None:
    """require_log_repo raises GuardError when origin remote does not match config."""
    run_git(["remote", "add", "origin", "https://github.com/user/correct.git"], cwd=git_repo)
    config = Config(
        log_repo_url="https://github.com/user/wrong.git",
        clone_path=str(git_repo),
        branch="main",
        github_email="user@example.com",
    )
    with pytest.raises(GuardError, match="Log repo origin URL mismatch") as exc_info:
        require_log_repo(config)
    assert "Refusing to write to wrong repository" in exc_info.value.hint


def test_require_log_repo_valid(git_repo: Path) -> None:
    """require_log_repo returns resolved path when clone is valid and origin matches."""
    run_git(["remote", "add", "origin", "https://github.com/user/correct.git"], cwd=git_repo)
    config = Config(
        log_repo_url="https://github.com/user/correct",
        clone_path=str(git_repo),
        branch="main",
        github_email="user@example.com",
    )
    resolved_path = require_log_repo(config)
    assert resolved_path == git_repo.resolve()


def test_require_remote_access_seeded_bare_remote(seeded_remote: Path) -> None:
    """require_remote_access succeeds with a reachable seeded bare remote."""
    require_remote_access(str(seeded_remote))


def test_require_remote_access_empty_bare_remote(bare_remote: Path) -> None:
    """require_remote_access treats empty repo without HEAD (returncode 2) as reachable."""
    require_remote_access(str(bare_remote))


def test_require_remote_access_unreachable_fails(tmp_path: Path) -> None:
    """require_remote_access raises GuardError when target cannot be accessed."""
    non_existent = tmp_path / "does_not_exist.git"
    with pytest.raises(GuardError, match="Cannot access remote repository") as exc_info:
        require_remote_access(str(non_existent))
    assert "Check repository URL" in exc_info.value.hint
