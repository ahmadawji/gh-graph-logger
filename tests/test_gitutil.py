"""Tests for gitutil module."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gh_graph_logger.gitutil import GitError, GitNotFoundError, run_git


def test_success_output_version() -> None:
    """run_git returns output without trailing newline on success."""
    output = run_git(["--version"])
    assert output.startswith("git version")
    assert not output.endswith("\n")
    assert not output.endswith("\r")


def test_success_output_in_repo(git_repo: Path) -> None:
    """run_git executes commands in git_repo directory."""
    msg = run_git(["log", "-1", "--format=%s"], cwd=git_repo)
    assert msg == "Initial commit"


def test_git_error_on_bad_command() -> None:
    """run_git raises GitError with details when check=True on failing command."""
    with pytest.raises(GitError) as exc_info:
        run_git(["not-a-valid-git-subcommand-xyz"])

    err = exc_info.value
    assert err.returncode is not None and err.returncode != 0
    assert err.command_args[0] == "git"
    assert "not-a-valid-git-subcommand-xyz" in err.command_args
    assert err.stderr != ""
    assert str(err) != ""


def test_bad_command_with_check_false() -> None:
    """run_git does not raise GitError when check=False."""
    output = run_git(["not-a-valid-git-subcommand-xyz"], check=False)
    assert isinstance(output, str)


def test_git_not_found_error_via_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_git raises GitNotFoundError if the git binary is missing."""
    def mock_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(GitNotFoundError) as exc_info:
        run_git(["status"])

    assert "executable not found" in str(exc_info.value)
    assert issubclass(GitNotFoundError, GitError)


def test_non_utf8_decoding_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_git decodes non-UTF-8 bytes using errors='replace' without crashing."""
    mock_process = subprocess.CompletedProcess(
        args=["git", "status"],
        returncode=0,
        stdout=b"non-utf8 \xff\xfe string\n",
        stderr=b"",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_process)

    output = run_git(["status"])
    assert "non-utf8" in output
    assert "\ufffd" in output
    assert not output.endswith("\n")


def test_timeout_raises_git_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_git raises GitError when command times out."""
    def mock_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(
            cmd=["git", "status"],
            timeout=5,
            stderr=b"Command timed out\n",
        )

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(GitError) as exc_info:
        run_git(["status"], timeout=5)

    err = exc_info.value
    assert "timed out after 5" in str(err)
    assert err.returncode is None
    assert "Command timed out" in err.stderr


def test_custom_env_passed_to_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_git merges and passes custom environment variables."""
    captured_kwargs: dict[str, object] = {}

    def mock_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            args=["git", "version"],
            returncode=0,
            stdout=b"git version 2.40\n",
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", mock_run)
    run_git(["version"], env={"TEST_CUSTOM_GIT_VAR": "custom_val"})

    env_used = captured_kwargs.get("env")
    assert isinstance(env_used, dict)
    assert env_used.get("TEST_CUSTOM_GIT_VAR") == "custom_val"
