"""Environment and repository guard checks for gh-graph-logger."""

from __future__ import annotations

import os
from pathlib import Path

from gh_graph_logger.config import Config
from gh_graph_logger.gitutil import GitError, GitNotFoundError, run_git


class GuardError(Exception):
    """Exception raised when an environment or repository guard check fails."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message: str = message
        self.hint: str = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message} (Hint: {self.hint})"
        return self.message


def normalize_repo_url(repository_url: str) -> str:
    """Normalize a git repository URL or local file path for reliable comparison.

    Strips leading/trailing whitespace, trailing slashes, trailing '.git', and standardizes
    path separators and Windows drive letter casing.
    """
    cleaned_url = repository_url.strip()

    # Strip file URL prefixes if present
    if cleaned_url.startswith("file:///"):
        cleaned_url = cleaned_url[8:]
    elif cleaned_url.startswith("file://"):
        cleaned_url = cleaned_url[7:]

    # Normalize backslashes to forward slashes
    cleaned_url = cleaned_url.replace("\\", "/")
    cleaned_url = cleaned_url.rstrip("/")

    # Normalize trailing '.git'
    if cleaned_url.endswith(".git"):
        cleaned_url = cleaned_url[:-4].rstrip("/")

    # If it is a Windows path with a drive letter, normalize drive letter casing
    drive, path_remainder = os.path.splitdrive(cleaned_url)
    if drive:
        cleaned_url = drive.lower() + path_remainder

    return cleaned_url


def require_git() -> str:
    """Verify that the git executable is installed and available on PATH.

    Returns:
        The git version string (e.g. 'git version 2.47.1').

    Raises:
        GuardError: If git is missing or cannot be executed.
    """
    try:
        output = run_git(["--version"])
        return output.strip()
    except GitNotFoundError as exception:
        raise GuardError(
            "git executable not found on system PATH.",
            hint="Install git and ensure it is available in your system PATH.",
        ) from exception
    except GitError as exception:
        raise GuardError(
            f"Failed to execute git: {exception.message}",
            hint="Ensure git is working properly.",
        ) from exception


def require_git_repo(cwd: str | Path | None = None) -> Path:
    """Verify that cwd (or the current working directory) is inside a git repository.

    Returns:
        The Path to the top-level directory of the git working tree.

    Raises:
        GuardError: If cwd is not inside a git repository.
    """
    try:
        output = run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
        return Path(output.strip()).resolve()
    except GitError as exception:
        raise GuardError(
            "Not inside a git repository.",
            hint="Run this command inside a git work repository.",
        ) from exception


def require_log_repo(config: Config) -> Path:
    """Verify that the configured log repository clone exists, is valid, and matches origin URL.

    Args:
        config: Loaded Config instance.

    Returns:
        The resolved Path to the log repository clone.

    Raises:
        GuardError: If the clone is missing, invalid, or origin URL does not match.
    """
    clone_path = Path(config.clone_path).resolve()
    if not clone_path.exists():
        raise GuardError(
            f"Log repo not found at '{config.clone_path}'.",
            hint="Run `ghlog init --path <new>` or `ghlog init --reclone`.",
        )

    if not clone_path.is_dir():
        raise GuardError(
            f"Log repo path '{config.clone_path}' is not a directory.",
            hint="Run `ghlog init --path <new>` or `ghlog init --reclone`.",
        )

    try:
        top_level = Path(run_git(["rev-parse", "--show-toplevel"], cwd=clone_path)).resolve()
    except GitError as exception:
        raise GuardError(
            f"Log repo clone at '{config.clone_path}' is not a git repository.",
            hint="Run `ghlog init --path <new>` or `ghlog init --reclone`.",
        ) from exception

    if top_level != clone_path:
        raise GuardError(
            f"Log repo clone at '{config.clone_path}' is not the root of a git repository "
            f"(found {top_level}).",
            hint="Run `ghlog init --path <new>` or `ghlog init --reclone`.",
        )

    try:
        origin_url = run_git(["remote", "get-url", "origin"], cwd=clone_path).strip()
    except GitError as exception:
        raise GuardError(
            f"Log repo clone at '{config.clone_path}' has no remote 'origin'.",
            hint="Run `ghlog init --reclone` or configure remote 'origin'.",
        ) from exception

    if normalize_repo_url(origin_url) != normalize_repo_url(config.log_repo_url):
        raise GuardError(
            f"Log repo origin URL mismatch: expected '{config.log_repo_url}', "
            f"found '{origin_url}'.",
            hint=(
                "Refusing to write to wrong repository. Check your configuration "
                "or run `ghlog init`."
            ),
        )

    return clone_path


def require_remote_access(repository_url: str) -> None:
    """Verify that the remote repository is reachable.

    Runs `git ls-remote --exit-code <url> HEAD` with GIT_TERMINAL_PROMPT=0.
    An empty remote repository with no HEAD (exit code 2) is considered reachable.

    Raises:
        GuardError: If the remote cannot be reached or does not exist.
    """
    try:
        run_git(
            ["ls-remote", "--exit-code", repository_url, "HEAD"],
            env={"GIT_TERMINAL_PROMPT": "0"},
            timeout=20,
            check=True,
        )
    except GitError as exception:
        if exception.returncode == 2:
            # Exit code 2 from `git ls-remote --exit-code` indicates an empty repo with no HEAD,
            # which is reachable and accessible.
            return

        error_detail = exception.stderr.strip() or exception.message
        raise GuardError(
            f"Cannot access remote repository at '{repository_url}': {error_detail}",
            hint="Check repository URL, network connection, and access permissions.",
        ) from exception
