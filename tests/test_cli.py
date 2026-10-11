"""Tests for gh-graph-logger CLI entry points and argument parsing."""

from __future__ import annotations

import pytest

from gh_graph_logger import __version__
from gh_graph_logger.cli import (
    ABORTED,
    ERROR,
    GUARD_FAILED,
    OK,
    main,
)


def test_exit_code_constants() -> None:
    """Ensure standard exit codes are defined."""
    assert OK == 0
    assert ERROR == 1
    assert GUARD_FAILED == 2
    assert ABORTED == 3


def test_no_subcommand_prints_help_and_returns_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Invoking without a subcommand prints help and returns exit code 1."""
    code = main([])
    assert code == ERROR
    captured = capsys.readouterr()
    assert "usage:" in captured.out or "usage:" in captured.err
    assert "subcommands" in captured.out or "subcommands" in captured.err


def test_help_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """Invoking with --help prints usage and exits with code 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "ghlog" in captured.out
    assert "init" in captured.out
    assert "check" in captured.out
    assert "collect" in captured.out
    assert "push" in captured.out
    assert "discard" in captured.out
    assert "config" in captured.out


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """Invoking with --version outputs version and exits with code 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


@pytest.mark.parametrize(
    "subcommand_args",
    [
        ["init"],
        ["init", "--root", "custom_root", "--path", "existing_clone", "--reclone"],
        ["check"],
        ["collect"],
        [
            "collect",
            "--since",
            "2026-01-01",
            "--author",
            "user@example.com",
            "--full",
            "--project",
            "test-proj",
        ],
        ["push"],
        ["push", "--yes"],
        ["discard"],
        ["config"],
        ["config", "--show"],
    ],
)
def test_subcommands_parse_and_return_error_stub(
    subcommand_args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """All subcommands currently print 'not implemented yet' and return 1."""
    code = main(subcommand_args)
    assert code == ERROR
    captured = capsys.readouterr()
    assert "not implemented yet" in captured.out
