"""Pytest fixtures for gh-graph-logger test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_graph_logger.gitutil import run_git


@pytest.fixture(autouse=True)
def isolate_git_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from user and system git configuration."""
    empty_global = tmp_path / "empty_global_gitconfig"
    empty_global.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_global))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def ghlog_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set GHLOG_HOME to a temporary directory for configuration isolation."""
    config_home_directory = tmp_path / "ghlog_home"
    config_home_directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GHLOG_HOME", str(config_home_directory))
    return config_home_directory


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with main branch and an initial commit."""
    repo_dir = tmp_path / "work_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Test User"], cwd=repo_dir)
    run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)

    readme = repo_dir / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    run_git(["add", "README.md"], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)

    return repo_dir


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """Create a temporary bare git repository representing a remote."""
    remote_dir = tmp_path / "remote.git"
    remote_dir.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--bare"], cwd=remote_dir)
    return remote_dir


@pytest.fixture
def seeded_remote(tmp_path: Path) -> Path:
    """Create a temporary bare git repository with an initial commit on main."""
    remote_directory = tmp_path / "seeded_remote.git"
    remote_directory.mkdir(parents=True, exist_ok=True)
    run_git(["init", "--bare", "-b", "main"], cwd=remote_directory)

    seed_clone_directory = tmp_path / "seed_clone"
    seed_clone_directory.mkdir(parents=True, exist_ok=True)
    run_git(["init", "-b", "main"], cwd=seed_clone_directory)
    run_git(["config", "user.name", "Seed User"], cwd=seed_clone_directory)
    run_git(["config", "user.email", "seed@example.com"], cwd=seed_clone_directory)

    readme_file = seed_clone_directory / "README.md"
    readme_file.write_text("# Seeded Remote Repo\n", encoding="utf-8")
    run_git(["add", "README.md"], cwd=seed_clone_directory)
    run_git(["commit", "-m", "Initial commit"], cwd=seed_clone_directory)
    run_git(["remote", "add", "origin", str(remote_directory)], cwd=seed_clone_directory)
    run_git(["push", "-u", "origin", "main"], cwd=seed_clone_directory)
    run_git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote_directory)

    return remote_directory
