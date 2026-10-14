"""Tests for gh-graph-logger CLI commands and unified daily flow."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gh_graph_logger import __version__
from gh_graph_logger.cli import (
    ABORTED,
    ERROR,
    GUARD_FAILED,
    OK,
    _configure_clone_identity,
    format_status,
    get_editor,
    main,
    normalize_url,
    repo_name_from_url,
    slugify,
)
from gh_graph_logger.config import Config, load_config, save_config
from gh_graph_logger.gitutil import run_git

# --------------------------------------------------------------------------
# General CLI tests: exit codes, help, version
# --------------------------------------------------------------------------


def test_exit_code_constants() -> None:
    """Ensure standard exit codes are defined."""
    assert OK == 0
    assert ERROR == 1
    assert GUARD_FAILED == 3
    assert ABORTED == 4


def test_help_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """Invoking with --help prints usage and exits with code 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "ghlog" in captured.out
    assert "init" in captured.out
    assert "check" in captured.out
    assert "config" in captured.out


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """Invoking with --version outputs version and exits with code 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


# --------------------------------------------------------------------------
# Helper function tests
# --------------------------------------------------------------------------


def test_slugify() -> None:
    """slugify converts arbitrary project names into URL- and filename-safe slugs."""
    assert slugify("My Project") == "my-project"
    assert slugify("Project_Name_123") == "project-name-123"
    assert slugify("---special@#$chars---") == "special-chars"
    assert slugify("") == "project"


def test_repo_name_from_url_sanitization() -> None:
    """repo_name_from_url sanitizes directory traversal characters."""
    assert repo_name_from_url("https://github.com/org/..") == "log-repo"
    assert repo_name_from_url("https://github.com/org/../") == "log-repo"
    assert repo_name_from_url("..") == "log-repo"
    assert repo_name_from_url(".") == "log-repo"
    assert repo_name_from_url("https://github.com/org/my-project.git") == "my-project"
    assert repo_name_from_url("https://github.com/org/my.project") == "my.project"


def test_format_status_encoding_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """format_status falls back to [OK] and [FAIL] when encoding does not support emoji."""
    import sys

    class DummyStream:
        encoding = "ascii"

    monkeypatch.setattr(sys, "stdout", DummyStream())
    assert format_status(True) == "[OK]"
    assert format_status(False) == "[FAIL]"


# --------------------------------------------------------------------------
# ghlog config tests
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
    assert "not configured - run ghlog init" in captured.err


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
    assert "Inside git repository: Not inside a git repository" in captured.err


def test_check_all_pass(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog check returns OK when all checks succeed."""
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

    user_email = run_git(["config", "user.email"], cwd=expected_target)
    assert user_email == "committer@example.com"

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
    assert not inside_root.exists()
    captured = capsys.readouterr()
    assert "Root directory cannot be inside an existing git repository" in captured.err


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


def test_init_path_to_moved_clone(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path
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

    config = load_config()
    assert config is not None
    assert config.clone_path == str(custom_clone.resolve())
    assert config.github_email == "custom@example.com"


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


def test_init_honors_branch_during_clone(
    ghlog_home: Path, seeded_remote: Path, tmp_path: Path
) -> None:
    """When --branch is supplied, clone creates and checks out the specified branch."""
    run_git(["branch", "feature-branch"], cwd=seeded_remote)
    root_dir = tmp_path / "branch_root"
    code = main(
        [
            "init",
            "--url",
            str(seeded_remote),
            "--email",
            "user@example.com",
            "--root",
            str(root_dir),
            "--branch",
            "feature-branch",
            "--yes",
        ]
    )
    assert code == OK
    target_clone = root_dir / "seeded_remote"
    current_branch = run_git(["branch", "--show-current"], cwd=target_clone).strip()
    assert current_branch == "feature-branch"


def test_configure_clone_identity_uses_local_and_delimiter(tmp_path: Path) -> None:
    """_configure_clone_identity uses --local and -- to prevent argument injection."""
    repo_dir = tmp_path / "test_identity_repo"
    run_git(["init", str(repo_dir)])

    args = argparse.Namespace(name="--system-test", yes=True)
    _configure_clone_identity(repo_dir, "test@example.com", args)

    email = run_git(["config", "--local", "user.email"], cwd=repo_dir).strip()
    name = run_git(["config", "--local", "user.name"], cwd=repo_dir).strip()
    assert email == "test@example.com"
    assert name == "--system-test"


# --------------------------------------------------------------------------
# ghlog daily workflow tests (Option A unified flow)
# --------------------------------------------------------------------------


def test_daily_outside_git_repo_fails(
    ghlog_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running ghlog outside a Git repository returns GUARD_FAILED."""
    outside_dir = tmp_path / "non_repo"
    outside_dir.mkdir()
    monkeypatch.chdir(outside_dir)

    code = main([])
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "Not inside a Git repository" in captured.err or "not a Git repository" in captured.err


def test_daily_not_configured_fails(
    ghlog_home: Path,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running ghlog before running init returns GUARD_FAILED."""
    monkeypatch.chdir(git_repo)
    code = main([])
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "not configured" in captured.err or "Run 'ghlog init'" in captured.err


def test_daily_no_commits_today(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running ghlog when no commits exist in the time window prints info and exits OK."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="test@example.com",
            last_push={},
        )
    )

    # Ask for commits since tomorrow to guarantee zero results
    tomorrow = "2099-01-01"
    code = main(["--since", tomorrow])
    assert code == OK
    captured = capsys.readouterr()
    assert "No commits found" in captured.out


def test_daily_happy_path(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Full daily flow: commits found, editor called, confirmed, pushed to log clone."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="test@example.com",
            last_push={},
        )
    )

    # Add a commit to git_repo
    feature_file = git_repo / "feature.txt"
    feature_file.write_text("amazing work", encoding="utf-8")
    run_git(["add", "feature.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Add amazing feature"], cwd=git_repo)

    # Mock editor to verify file contents and leave it unchanged
    editor_called = MagicMock()

    def mock_open_editor(file_path: Path) -> None:
        editor_called(file_path)
        content = file_path.read_text(encoding="utf-8")
        assert "Add amazing feature" in content

    monkeypatch.setattr("gh_graph_logger.cli.open_editor", mock_open_editor)
    # Mock user input to confirm push
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    code = main(["--since", "2000-01-01"])
    assert code == OK
    editor_called.assert_called_once()

    captured = capsys.readouterr()
    assert "Successfully logged 2 commit(s)" in captured.out  # Initial commit + Add amazing feature

    # Verify log entry in clone
    project_slug = slugify(git_repo.name)
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_file = clone_dir / project_slug / f"{today_str}.md"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Add amazing feature" in content
    assert f"# {project_slug}" in content

    # Verify last_push updated in config
    updated_cfg = load_config()
    assert updated_cfg is not None
    assert project_slug in updated_cfg.last_push


def test_daily_editor_clears_all_commits_aborts(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When user deletes all commits in the editor, logging is cancelled."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="test@example.com",
            last_push={},
        )
    )

    def mock_empty_editor(file_path: Path) -> None:
        # Erase everything
        file_path.write_text("# Only comments\n", encoding="utf-8")

    monkeypatch.setattr("gh_graph_logger.cli.open_editor", mock_empty_editor)

    code = main(["--since", "2000-01-01"])
    assert code == OK
    captured = capsys.readouterr()
    assert "No commits left in draft. Cancelled." in captured.out


def test_daily_user_declines_push_prompt(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When user inputs 'n' at confirmation prompt, logging is aborted."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="test@example.com",
            last_push={},
        )
    )

    monkeypatch.setattr("gh_graph_logger.cli.open_editor", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    code = main(["--since", "2000-01-01"])
    assert code == ABORTED
    captured = capsys.readouterr()
    assert "Aborted. Draft discarded." in captured.out


def test_daily_with_yes_flag_skips_prompt(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When --yes is provided, user is not prompted for confirmation."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="test@example.com",
            last_push={},
        )
    )

    monkeypatch.setattr("gh_graph_logger.cli.open_editor", lambda p: None)

    # If input is called, raise error
    def fail_if_prompted(p: str) -> str:
        pytest.fail("input() should not be called when --yes is passed")

    monkeypatch.setattr("builtins.input", fail_if_prompted)

    code = main(["--since", "2000-01-01", "--yes"])
    assert code == OK
    captured = capsys.readouterr()
    assert "Successfully logged" in captured.out


def test_daily_collect_alias_works_identically(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The 'collect' subcommand works as a direct alias for the daily flow."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="test@example.com",
            last_push={},
        )
    )

    monkeypatch.setattr("gh_graph_logger.cli.open_editor", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda p: "y")

    code = main(["collect", "--since", "2000-01-01", "--project", "alias-test"])
    assert code == OK
    captured = capsys.readouterr()
    assert "Successfully logged 1 commit(s) for 'alias-test'" in captured.out


def test_init_rejects_ext_protocol(
    ghlog_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog init rejects dangerous custom transport protocols like ext:: and fd::."""
    root_dir = tmp_path / "root_dir"
    code = main(
        [
            "init",
            "--url=ext::sh -c evil",
            "--email",
            "user@example.com",
            "--root",
            str(root_dir),
            "--yes",
        ]
    )
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "Dangerous or unsupported git protocol" in captured.err


def test_check_with_empty_remote_succeeds(
    ghlog_home: Path,
    git_repo: Path,
    bare_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog check reports OK when remote returns exit code 2 (empty bare repository)."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(bare_remote), str(clone_dir)])

    save_config(
        Config(
            log_repo_url=str(bare_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="user@example.com",
        )
    )

    code = main(["check"])
    assert code == OK
    captured = capsys.readouterr()
    assert "Remote access" in captured.out
    assert "empty repository" in captured.out


def test_init_path_nested_subfolder_fails(
    ghlog_home: Path,
    seeded_remote: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog init --path rejects a subfolder inside a git repository that is not the root."""
    clone_dir = tmp_path / "parent_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    nested_dir = clone_dir / "nested_subfolder"
    nested_dir.mkdir()

    code = main(
        [
            "init",
            "--path",
            str(nested_dir),
            "--email",
            "user@example.com",
            "--yes",
        ]
    )
    assert code == ERROR
    captured = capsys.readouterr()
    assert "is not the root of a git repository" in captured.err


def test_daily_push_failure_does_not_update_last_push(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When git push fails, daily returns ERROR and does not advance last_push."""
    monkeypatch.chdir(git_repo)
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])

    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="test@example.com",
            last_push={},
        )
    )

    # Add commit to work repo
    feature_file = git_repo / "new_work.txt"
    feature_file.write_text("work details", encoding="utf-8")
    run_git(["add", "new_work.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Work in progress"], cwd=git_repo)

    monkeypatch.setattr("gh_graph_logger.cli.open_editor", lambda p: None)

    # Mock run_git so that push fails with GitError
    from gh_graph_logger.gitutil import GitError
    real_run_git = run_git

    def mock_run_git(args: list[str], *a: object, **kw: object) -> str:
        if args and args[0] == "push":
            raise GitError("Simulated network timeout during push", command_args=args, returncode=1)
        return real_run_git(args, *a, **kw)

    monkeypatch.setattr("gh_graph_logger.cli.run_git", mock_run_git)

    code = main(["--since", "2000-01-01", "--yes"])
    assert code == ERROR

    captured = capsys.readouterr()
    assert "push failed" in captured.err
    assert "preserved locally" in captured.err

    # Crucial assertion: last_push was NOT updated
    cfg = load_config()
    assert cfg is not None
    project_slug = slugify(git_repo.name)
    assert project_slug not in cfg.last_push


def test_get_editor_strips_quotes_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_editor strips quotes from executable tokens on Windows."""
    monkeypatch.setenv("GIT_EDITOR", '"C:\\Program Files\\VS Code\\Code.exe" --wait')
    editor_cmd = get_editor()
    assert editor_cmd[0] == "C:\\Program Files\\VS Code\\Code.exe"
    assert editor_cmd[1] == "--wait"


def test_normalize_url_ssh_and_https() -> None:
    """normalize_url standardizes SSH vs HTTPS and backslashes."""
    ssh_url = "git@github.com:myorg/myrepo.git"
    https_url = "https://github.com/myorg/myrepo"
    ssh_scheme = "ssh://git@github.com/myorg/myrepo.git"
    http_url = "http://github.com/myorg/myrepo.git"

    assert normalize_url(ssh_url) == "https://github.com/myorg/myrepo"
    assert normalize_url(https_url) == "https://github.com/myorg/myrepo"
    assert normalize_url(ssh_scheme) == "https://github.com/myorg/myrepo"
    assert normalize_url(http_url) == "https://github.com/myorg/myrepo"

    # Windows local path with backslashes
    assert normalize_url(r"C:\Users\repo.git") == "c:/users/repo"

