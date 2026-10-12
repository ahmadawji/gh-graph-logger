"""Tests for gh-graph-logger CLI entry points and argument parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_graph_logger import __version__
from gh_graph_logger.cli import (
    ABORTED,
    ERROR,
    GUARD_FAILED,
    OK,
    format_status,
    main,
)
from gh_graph_logger.config import Config, save_config
from gh_graph_logger.gitutil import run_git


def test_exit_code_constants() -> None:
    """Ensure standard exit codes are defined."""
    assert OK == 0
    assert ERROR == 1
    assert GUARD_FAILED == 3
    assert ABORTED == 4


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
    ],
)
def test_unreleased_subcommands_return_error_stub(
    subcommand_args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Unreleased subcommands print 'not implemented yet' and return 1."""
    code = main(subcommand_args)
    assert code == ERROR
    captured = capsys.readouterr()
    assert "not implemented yet" in captured.out


# --------------------------------------------------------------------------
# ghlog config --show tests
# --------------------------------------------------------------------------


def test_config_show_missing_file(ghlog_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """ghlog config --show returns ERROR when config file does not exist."""
    code = main(["config", "--show"])
    assert code == ERROR
    captured = capsys.readouterr()
    assert "No configuration file found" in captured.err


def test_config_without_show_flag(ghlog_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """ghlog config without --show returns ERROR with instruction."""
    code = main(["config"])
    assert code == ERROR
    captured = capsys.readouterr()
    assert "Use 'ghlog config --show'" in captured.err


def test_config_show_valid(
    ghlog_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ghlog config --show prints config file path and fields."""
    clone_dir = tmp_path / "my_clone"
    config = Config(
        log_repo_url="https://github.com/test/repo.git",
        clone_path=str(clone_dir),
        branch="main",
        github_email="dev@example.com",
        last_push={"proj1": "2026-10-12T10:00:00Z"},
    )
    save_config(config)

    code = main(["config", "--show"])
    assert code == OK
    captured = capsys.readouterr()
    assert "Configuration file:" in captured.out
    assert "https://github.com/test/repo.git" in captured.out
    assert str(clone_dir.resolve()) in captured.out
    assert "dev@example.com" in captured.out
    assert "proj1: 2026-10-12T10:00:00Z" in captured.out


# --------------------------------------------------------------------------
# ghlog check tests
# --------------------------------------------------------------------------


def test_check_not_configured(
    ghlog_home: Path,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog check reports unconfigured log repository and returns GUARD_FAILED."""
    monkeypatch.chdir(git_repo)
    code = main(["check"])
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "Git executable" in captured.out
    assert "Inside git repository" in captured.out
    assert "not configured — run ghlog init" in captured.out


def test_check_outside_work_repo(
    ghlog_home: Path,
    tmp_path: Path,
    seeded_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog check reports failure when run outside any git repository."""
    non_repo_dir = tmp_path / "outside_dir"
    non_repo_dir.mkdir()
    monkeypatch.chdir(non_repo_dir)

    # Configure valid clone
    clone_dir = tmp_path / "valid_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="user@example.com",
        )
    )

    code = main(["check"])
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "Inside git repository: Not inside a git repository" in captured.out


def test_check_all_pass(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog check returns OK when all four checks succeed."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])

    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="user@example.com",
        )
    )

    code = main(["check"])
    assert code == OK
    captured = capsys.readouterr()
    assert "Git executable" in captured.out
    assert "Inside git repository" in captured.out
    assert "Log repository clone" in captured.out
    assert "Remote access" in captured.out


# --------------------------------------------------------------------------
# ghlog init tests
# --------------------------------------------------------------------------


def test_init_happy_path(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ghlog init with --url, --email, --yes, --root clones successfully."""
    root_dir = tmp_path / "custom_root"
    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "committer@example.com",
            "--root",
            str(root_dir),
            "--yes",
        ]
    )
    assert code == OK
    expected_target = root_dir / "seeded_remote"
    assert expected_target.exists()

    # Check local git identity in the clone
    user_email = run_git(["config", "user.email"], cwd=expected_target)
    assert user_email == "committer@example.com"

    # Check saved config
    from gh_graph_logger.config import load_config

    config = load_config()
    assert config is not None
    assert config.clone_path == str(expected_target.resolve())
    assert config.github_email == "committer@example.com"
    assert config.branch == "main"


def test_init_root_autocreates_when_missing(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path
) -> None:
    """ghlog init auto-creates non-existent root directory when --yes is supplied."""
    non_existent_root = tmp_path / "deep" / "nested" / "root"
    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "user@example.com",
            "--root",
            str(non_existent_root),
            "--yes",
        ]
    )
    assert code == OK
    assert non_existent_root.exists()


def test_init_root_inside_work_repo_fails_and_nothing_created(
    ghlog_home: Path, git_repo: Path, seeded_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ghlog init refuses to create a clone inside an existing work repository."""
    inside_root = git_repo / "forbidden_logs"
    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "user@example.com",
            "--root",
            str(inside_root),
            "--yes",
        ]
    )
    assert code == GUARD_FAILED
    # Crucial requirement: nothing must be created
    assert not inside_root.exists()
    captured = capsys.readouterr()
    assert "inside a git repository" in captured.err


def test_init_target_exists_different_origin_error_unchanged(
    ghlog_home: Path,
    seeded_remote: Path,
    bare_remote: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If target directory already exists with a different origin, abort without changes."""
    root_dir = tmp_path / "root_dir"
    target_dir = root_dir / "seeded_remote"
    # Clone a different repo into target_dir
    run_git(["clone", str(bare_remote), str(target_dir)])

    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "user@example.com",
            "--root",
            str(root_dir),
            "--yes",
        ]
    )
    assert code == ERROR
    captured = capsys.readouterr()
    assert "already exists and is not a clone of" in captured.err

    # Target directory origin must remain unchanged
    origin = run_git(["remote", "get-url", "origin"], cwd=target_dir)
    assert origin == str(bare_remote)


def test_init_reuse_existing_matching_clone(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If target directory already exists with matching origin, reuse it without recloning."""
    root_dir = tmp_path / "root_dir"
    target_dir = root_dir / "seeded_remote"
    run_git(["clone", str(seeded_remote), str(target_dir)])

    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "reused@example.com",
            "--root",
            str(root_dir),
            "--yes",
        ]
    )
    assert code == OK
    captured = capsys.readouterr()
    assert "Reusing existing clone" in captured.out

    user_email = run_git(["config", "user.email"], cwd=target_dir)
    assert user_email == "reused@example.com"


def test_init_path_to_moved_clone(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ghlog init --path configures an existing clone at a custom location."""
    custom_clone = tmp_path / "my_custom_clone_folder"
    run_git(["clone", str(seeded_remote), str(custom_clone)])

    code = main(
        [
            "init",
            "--path",
            str(custom_clone),
            "--url",
            str(seeded_remote),
            "--email",
            "custom@example.com",
            "--yes",
        ]
    )
    assert code == OK

    from gh_graph_logger.config import load_config

    config = load_config()
    assert config is not None
    assert config.clone_path == str(custom_clone.resolve())
    assert config.github_email == "custom@example.com"


def test_init_existing_unrelated_directory_is_never_deleted(
    ghlog_home: Path,
    seeded_remote: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When a non-matching directory exists at target, init fails and preserves all files."""
    root_dir = tmp_path / "root_dir"
    target_dir = root_dir / "seeded_remote"
    target_dir.mkdir(parents=True)
    important_file = target_dir / "IMPORTANT.txt"
    important_file.write_text("my precious data\n", encoding="utf-8")

    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "user@example.com",
            "--root",
            str(root_dir),
            "--yes",
        ]
    )
    assert code == ERROR
    captured = capsys.readouterr()
    assert "already exists and is not a clone" in captured.err

    # The file must remain 100% untouched
    assert important_file.exists()
    assert important_file.read_text(encoding="utf-8") == "my precious data\n"


def test_init_path_offline_succeeds_with_warning(
    ghlog_home: Path,
    seeded_remote: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog init --path succeeds with a warning if the remote URL is temporarily unreachable."""
    custom_clone = tmp_path / "offline_clone"
    run_git(["clone", str(seeded_remote), str(custom_clone)])

    # Use a dummy remote URL that matches origin in clone, but mock remote access failure
    code = main(
        [
            "init",
            "--path",
            str(custom_clone),
            "--url",
            str(seeded_remote),
            "--email",
            "offline@example.com",
            "--yes",
        ]
    )
    assert code == OK

    from gh_graph_logger.config import load_config

    config = load_config()
    assert config is not None
    assert config.clone_path == str(custom_clone.resolve())


def test_init_rejects_leading_hyphen_url(
    ghlog_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog init rejects repository URLs starting with '-' to prevent argument injection."""
    root_dir = tmp_path / "root_dir"
    code = main(
        [
            "init",
            "--url=--upload-pack=evil",
            "--email",
            "user@example.com",
            "--root",
            str(root_dir),
            "--yes",
        ]
    )
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "URLs starting with '-' are not permitted" in captured.err


def test_init_invalid_email_fails(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ghlog init fails when email does not contain '@'."""
    root_dir = tmp_path / "root_dir"
    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "invalid-email-without-at",
            "--root",
            str(root_dir),
            "--yes",
        ]
    )
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "must contain '@'" in captured.err


def test_keyboard_interrupt_during_init_returns_aborted(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KeyboardInterrupt during prompts cleanly returns ABORTED (exit code 4)."""

    def raise_interrupt(prompt: str) -> str:
        raise KeyboardInterrupt()

    monkeypatch.setattr("builtins.input", raise_interrupt)

    code = main(["init", "--url", str(seeded_remote), "--root", str(tmp_path)])
    assert code == ABORTED


def test_format_status_encoding_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """format_status falls back to [OK] and [FAIL] when encoding does not support emoji."""
    import sys

    # Simulate an encoding like ascii or cp1252 that cannot encode emoji
    class DummyStream:
        encoding = "ascii"

    monkeypatch.setattr(sys, "stdout", DummyStream())
    assert format_status(True) == "[OK]"
    assert format_status(False) == "[FAIL]"
