"""Git utility functions and exceptions for gh-graph-logger."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(Exception):
    """Exception raised when a git command fails or times out."""

    def __init__(
        self,
        message: str,
        cmd: list[str] | None = None,
        returncode: int | None = None,
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.cmd: list[str] = list(cmd) if cmd is not None else []
        self.returncode: int | None = returncode
        self.stderr: str = stderr

    def __str__(self) -> str:
        return self.message


class GitNotFoundError(GitError):
    """Exception raised when the git executable is not found on PATH."""

    def __init__(
        self,
        message: str = "git executable not found on system PATH",
        cmd: list[str] | None = None,
    ) -> None:
        super().__init__(message=message, cmd=cmd, returncode=None, stderr="")


def run_git(
    args: list[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = 30,
    check: bool = True,
) -> str:
    """Execute a git command safely and return its decoded stdout.

    Args:
        args: Command arguments for git (e.g. ['status'] or ['commit', '-m', 'msg']).
              Do not include the leading 'git' command name.
        cwd: Working directory in which to execute the command.
        env: Optional environment variables to merge with os.environ.
        timeout: Maximum execution time in seconds. Defaults to 30.
        check: If True, raise GitError on non-zero return codes.

    Returns:
        The decoded stdout output with trailing newline stripped.

    Raises:
        GitNotFoundError: If git binary is missing from PATH.
        GitError: If command times out or returns non-zero when check=True.
    """
    cmd: list[str] = ["git", *args]

    proc_env = None
    if env is not None:
        proc_env = os.environ.copy()
        proc_env.update(env)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            env=proc_env,
            capture_output=True,
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise GitNotFoundError(
            message=f"git executable not found: {cmd[0]}",
            cmd=cmd,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        stderr_bytes = exc.stderr if isinstance(exc.stderr, bytes) else b""
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")
        raise GitError(
            message=f"git command timed out after {timeout}s: {' '.join(cmd)}",
            cmd=cmd,
            returncode=None,
            stderr=stderr_str,
        ) from exc

    stdout_str = proc.stdout.decode("utf-8", errors="replace")
    stderr_str = proc.stderr.decode("utf-8", errors="replace")

    if check and proc.returncode != 0:
        err_msg = stderr_str.strip() or stdout_str.strip() or f"exit code {proc.returncode}"
        raise GitError(
            message=f"git command failed ({' '.join(cmd)}): {err_msg}",
            cmd=cmd,
            returncode=proc.returncode,
            stderr=stderr_str,
        )

    # Strip single trailing newline (\r\n or \n)
    if stdout_str.endswith("\r\n"):
        return stdout_str[:-2]
    if stdout_str.endswith("\n"):
        return stdout_str[:-1]
    return stdout_str
