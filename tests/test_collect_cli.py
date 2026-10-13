"""End-to-end CLI tests for `ghlog collect`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from gh_graph_logger.cli import ABORTED, ERROR, GUARD_FAILED, OK, main
from gh_graph_logger.config import Config, save_config
from gh_graph_logger.draft import draft_path
from gh_graph_logger.gitutil import run_git


@pytest.fixture
def configured_environment(
    ghlog_home: Path,
    git_repo: Path,
    seeded_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Fixture providing a valid work repo and configured log repo clone."""
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="dev@example.com",
        )
    )
    run_git(["config", "--local", "ghlog.project", "work-repo"], cwd=git_repo)
    monkeypatch.chdir(git_repo)
    return git_repo


def test_collect_outside_git_repo(
    ghlog_home: Path,
    tmp_path: Path,
    seeded_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog collect outside a git repo fails guard and returns GUARD_FAILED."""
    clone_dir = tmp_path / "log_clone"
    run_git(["clone", str(seeded_remote), str(clone_dir)])
    save_config(
        Config(
            log_repo_url=str(seeded_remote),
            clone_path=str(clone_dir),
            branch="main",
            github_email="dev@example.com",
        )
    )
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    monkeypatch.chdir(outside_dir)

    code = main(["collect"])
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "Not inside a git repository" in captured.err


def test_collect_not_configured(
    ghlog_home: Path,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ghlog collect without init fails guard and returns GUARD_FAILED."""
    monkeypatch.chdir(git_repo)
    code = main(["collect"])
    assert code == GUARD_FAILED
    captured = capsys.readouterr()
    assert "not configured" in captured.err
    assert "ghlog init" in captured.err


def test_collect_invalid_since_format(
    configured_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ghlog collect with invalid --since prints error and returns ERROR."""
    code = main(["collect", "--since", "invalid-date"])
    assert code == ERROR
    captured = capsys.readouterr()
    assert "Invalid date/time format for --since" in captured.err


def test_collect_zero_commits_found(
    configured_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ghlog collect with 0 commits in window creates no file and returns OK."""
    # Since future date
    code = main(["collect", "--since", "2099-01-01"])
    assert code == OK
    captured = capsys.readouterr()
    assert "No commits found since" in captured.out
    assert "Nothing to log." in captured.out

    # Ensure draft was not created
    draft_file = draft_path(configured_environment)
    assert not draft_file.exists()


def test_collect_happy_path_editor_deletes_one_line(
    configured_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Happy path: 3 commits collected, editor deletes 1, draft saved with 2 commits."""
    email = "test@example.com"
    today_iso = datetime.now().astimezone().strftime("%Y-%m-%dT12:00:00")
    env = {
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": today_iso,
        "GIT_COMMITTER_DATE": today_iso,
    }

    for i in range(1, 3):
        file_path = configured_environment / f"file_{i}.txt"
        file_path.write_text(f"content {i}", encoding="utf-8")
        run_git(["add", f"file_{i}.txt"], cwd=configured_environment)
        run_git(["commit", "-m", f"Commit number {i}"], cwd=configured_environment, env=env)

    # Simulate editor by removing the last commit line
    def fake_editor(repo_root: Path, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Find bullet lines and remove the last one
        bullet_indices = [idx for idx, line in enumerate(lines) if line.startswith("- ")]
        if bullet_indices:
            del lines[bullet_indices[-1]]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    from gh_graph_logger import draft
    monkeypatch.setattr(draft, "open_editor", fake_editor)

    code = main(["collect", "--project", "demo-project"])
    assert code == OK
    captured = capsys.readouterr()
    assert "Draft saved to" in captured.out
    assert "2 commits" in captured.out
    assert "Publishing arrives in the next phase." in captured.out

    draft_file = draft_path(configured_environment)
    assert draft_file.exists()
    final_content = draft_file.read_text(encoding="utf-8")
    bullet_count = sum(1 for line in final_content.splitlines() if line.startswith("- "))
    assert bullet_count == 2
    assert "## demo-project —" in final_content
    # Comments should have been stripped
    assert "# Lines starting with" not in final_content


def test_collect_editor_empties_everything_aborts_and_deletes_draft(
    configured_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When user deletes all commits in editor, collect aborts and unlinks the draft."""
    today_iso = datetime.now().astimezone().strftime("%Y-%m-%dT12:00:00")
    env = {
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": today_iso,
        "GIT_COMMITTER_DATE": today_iso,
    }
    (configured_environment / "file.txt").write_text("hello", encoding="utf-8")
    run_git(["add", "file.txt"], cwd=configured_environment)
    run_git(["commit", "-m", "A commit"], cwd=configured_environment, env=env)

    def fake_editor_empty(repo_root: Path, path: Path) -> None:
        # User clears file or leaves only comments
        path.write_text("# Only a comment remains\n", encoding="utf-8")

    from gh_graph_logger import draft
    monkeypatch.setattr(draft, "open_editor", fake_editor_empty)

    code = main(["collect"])
    assert code == ABORTED
    captured = capsys.readouterr()
    assert "Nothing to log - draft discarded." in captured.out

    draft_file = draft_path(configured_environment)
    assert not draft_file.exists()


def test_collect_existing_draft_prompt_cancel_reopen_overwrite(
    configured_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify handling when draft already exists: cancel, reopen, overwrite."""
    draft_file = draft_path(configured_environment)
    initial_draft_content = (
        "## existing-project — 2026-10-13 10:00\n\n"
        "- 10:00 `abc1234` Existing commit 1\n"
        "- 10:05 `def5678` Existing commit 2\n"
    )

    # 1. Cancel option ('c')
    draft_file.write_text(initial_draft_content, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "c")
    code_cancel = main(["collect"])
    assert code_cancel == ABORTED
    assert draft_file.exists()
    assert draft_file.read_text(encoding="utf-8") == initial_draft_content

    # 2. Reopen option ('r')
    reopened = False

    def fake_editor_reopen(repo_root: Path, path: Path) -> None:
        nonlocal reopened
        reopened = True

    from gh_graph_logger import draft
    monkeypatch.setattr(draft, "open_editor", fake_editor_reopen)
    monkeypatch.setattr("builtins.input", lambda _: "r")

    code_reopen = main(["collect"])
    assert code_reopen == OK
    assert reopened is True

    # 3. Overwrite option ('o')
    overwritten = False

    def fake_editor_overwrite(repo_root: Path, path: Path) -> None:
        nonlocal overwritten
        overwritten = True

    # Add a commit today
    today_iso = datetime.now().astimezone().strftime("%Y-%m-%dT12:00:00")
    env = {
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": today_iso,
        "GIT_COMMITTER_DATE": today_iso,
    }
    (configured_environment / "fresh.txt").write_text("fresh", encoding="utf-8")
    run_git(["add", "fresh.txt"], cwd=configured_environment)
    run_git(["commit", "-m", "Fresh commit"], cwd=configured_environment, env=env)

    monkeypatch.setattr(draft, "open_editor", fake_editor_overwrite)
    monkeypatch.setattr("builtins.input", lambda _: "o")

    code_overwrite = main(["collect"])
    assert code_overwrite == OK
    assert overwritten is True
    fresh_content = draft_file.read_text(encoding="utf-8")
    assert "Fresh commit" in fresh_content


def test_collect_editor_missing_returns_error(
    configured_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When editor binary cannot be found, collect returns ERROR with hint."""
    today_iso = datetime.now().astimezone().strftime("%Y-%m-%dT12:00:00")
    env = {
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": today_iso,
        "GIT_COMMITTER_DATE": today_iso,
    }
    (configured_environment / "some_file.txt").write_text("hello", encoding="utf-8")
    run_git(["add", "some_file.txt"], cwd=configured_environment)
    run_git(["commit", "-m", "Some commit"], cwd=configured_environment, env=env)

    # Set non-existent editor
    run_git(["config", "core.editor", "missing_editor_bin_12345"], cwd=configured_environment)

    code = main(["collect"])
    assert code == ERROR
    captured = capsys.readouterr()
    assert "core.editor" in captured.err


def test_collect_prompts_project_name_when_not_configured(
    configured_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When ghlog.project is not configured in repo, collect prompts user and saves answer."""
    # Unset ghlog.project
    run_git(
        ["config", "--local", "--unset", "ghlog.project"],
        cwd=configured_environment,
        check=False,
    )
    monkeypatch.setattr("builtins.input", lambda _: "first-prompt-project")

    from gh_graph_logger import draft
    monkeypatch.setattr(draft, "open_editor", lambda repo_root, path: None)

    code = main(["collect"])
    assert code == OK

    stored_project = run_git(
        ["config", "--local", "ghlog.project"], cwd=configured_environment
    ).strip()
    assert stored_project == "first-prompt-project"


def test_collect_full_body_bullets_emptied_real_bullets_aborts(
    configured_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Deleting the root commit bullet while leaving indented body bullets aborts as empty."""
    today_iso = datetime.now().astimezone().strftime("%Y-%m-%dT12:00:00")
    env = {
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": today_iso,
        "GIT_COMMITTER_DATE": today_iso,
    }
    (configured_environment / "bullet_file.txt").write_text("hello", encoding="utf-8")
    run_git(["add", "bullet_file.txt"], cwd=configured_environment)
    run_git(
        ["commit", "-m", "A commit with sub bullets", "-m", "- item one\n- item two"],
        cwd=configured_environment,
        env=env,
    )

    def fake_editor_delete_root_bullet(repo_root: Path, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        # Keep only lines that don't start with "- " at column 0
        new_lines = [line for line in content.splitlines() if not line.startswith("- ")]
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    from gh_graph_logger import draft
    monkeypatch.setattr(draft, "open_editor", fake_editor_delete_root_bullet)

    code = main(["collect", "--full"])
    assert code == ABORTED
    captured = capsys.readouterr()
    assert "Nothing to log - draft discarded." in captured.out


def test_collect_reopen_reappends_instructions_if_missing(
    configured_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When reopening an existing draft without comments, instructions are re-appended."""
    draft_file = draft_path(configured_environment)
    # Draft with commits but no '# ' instructions
    clean_draft = "## demo — 2026-10-13 10:00\n\n- 10:00 `abcdef0` Some commit\n"
    draft_file.write_text(clean_draft, encoding="utf-8")

    saw_instructions_in_editor = False

    def fake_editor_check_instructions(repo_root: Path, path: Path) -> None:
        nonlocal saw_instructions_in_editor
        text = path.read_text(encoding="utf-8")
        if "# Lines starting with '#' are comments" in text:
            saw_instructions_in_editor = True

    from gh_graph_logger import draft
    monkeypatch.setattr(draft, "open_editor", fake_editor_check_instructions)
    monkeypatch.setattr("builtins.input", lambda _: "r")

    code = main(["collect"])
    assert code == OK
    assert saw_instructions_in_editor is True
