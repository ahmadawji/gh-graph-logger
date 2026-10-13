"""Unit tests for commit collection and author/window resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gh_graph_logger.collector import (
    collect_commits,
    compute_window_start,
    parse_since,
    resolve_author_emails,
)
from gh_graph_logger.gitutil import run_git
from gh_graph_logger.guards import GuardError


def test_parse_since_valid_formats() -> None:
    """parse_since parses YYYY-MM-DD, YYYY-MM-DD HH:MM, and ISO strings."""
    # Date only -> local midnight
    result_date = parse_since("2026-10-13")
    assert result_date.year == 2026
    assert result_date.month == 10
    assert result_date.day == 13
    assert result_date.hour == 0
    assert result_date.minute == 0
    assert result_date.tzinfo is not None

    # Date and time
    result_dt = parse_since("2026-10-13 15:45")
    assert result_dt.year == 2026
    assert result_dt.month == 10
    assert result_dt.day == 13
    assert result_dt.hour == 15
    assert result_dt.minute == 45
    assert result_dt.tzinfo is not None

    # ISO datetime with offset
    result_iso = parse_since("2026-10-13T12:00:00+02:00")
    assert result_iso.year == 2026
    assert result_iso.hour == 12
    assert result_iso.tzinfo is not None


@pytest.mark.parametrize(
    "invalid_text",
    [
        "",
        "   ",
        "yesterday",
        "2026/10/13",
        "2026-99-99",
        "not-a-date",
    ],
)
def test_parse_since_invalid_raises_value_error(invalid_text: str) -> None:
    """parse_since raises ValueError with helpful message on invalid formats."""
    with pytest.raises(ValueError, match="Invalid"):
        parse_since(invalid_text)


def test_compute_window_start() -> None:
    """compute_window_start handles override, last_push, and midnight fallback."""
    now = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
    midnight_today = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)

    # 1. Override is always respected
    override = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    assert compute_window_start("demo", {}, now, since_override=override) == override

    # 2. No last_push -> midnight today
    assert compute_window_start("demo", {}, now) == midnight_today

    # 3. Last push was earlier today (10:00 > 00:00) -> returns last_push
    last_push_today = {"demo": "2026-10-13T10:00:00+00:00"}
    expected_push = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)
    assert compute_window_start("demo", last_push_today, now) == expected_push

    # 4. Last push was yesterday (2026-10-12 < midnight today) -> returns midnight today
    last_push_yesterday = {"demo": "2026-10-12T20:00:00+00:00"}
    assert compute_window_start("demo", last_push_yesterday, now) == midnight_today

    # 5. Corrupt last_push timestamp ignored -> returns midnight today
    last_push_corrupt = {"demo": "corrupt-iso-string"}
    assert compute_window_start("demo", last_push_corrupt, now) == midnight_today


def test_resolve_author_emails(git_repo: Path) -> None:
    """resolve_author_emails priority: override > ghlog.author > user.email."""
    # 1. Default from git_repo fixture (user.email = 'test@example.com')
    assert resolve_author_emails(git_repo) == ["test@example.com"]

    # 2. Local config ghlog.author
    run_git(
        ["config", "--local", "ghlog.author", "alice@example.com, bob@example.com"],
        cwd=git_repo,
    )
    assert resolve_author_emails(git_repo) == ["alice@example.com", "bob@example.com"]

    # 3. Override takes precedence
    override_result = resolve_author_emails(
        git_repo, override="charlie@example.com, dave@example.com"
    )
    assert override_result == ["charlie@example.com", "dave@example.com"]


def test_resolve_author_emails_missing_raises_guard_error(tmp_path: Path) -> None:
    """When no author email is configured, resolve_author_emails raises GuardError."""
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    run_git(["init"], cwd=empty_repo)
    # Ensure no user.email is set locally or globally
    run_git(["config", "--local", "--unset-all", "user.email"], cwd=empty_repo, check=False)

    with pytest.raises(GuardError, match="No author email"):
        resolve_author_emails(empty_repo)


def test_collect_commits_author_filtering_and_regex_safety(git_repo: Path) -> None:
    """collect_commits filters out teammates and handles regex metachars safely."""
    # Author email: a@b.c (contains dot regex metacharacter)
    run_git(["config", "user.email", "a@b.c"], cwd=git_repo)

    env_author = {
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "a@b.c",
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "a@b.c",
        "GIT_AUTHOR_DATE": "2026-10-13T10:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T10:00:00+00:00",
    }
    (git_repo / "alice.txt").write_text("alice", encoding="utf-8")
    run_git(["add", "alice.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit by Alice"], cwd=git_repo, env=env_author)

    # Teammate commit with similar email: xa@b.cd (should NOT match)
    env_teammate_1 = {
        "GIT_AUTHOR_NAME": "Teammate 1",
        "GIT_AUTHOR_EMAIL": "xa@b.cd",
        "GIT_COMMITTER_NAME": "Teammate 1",
        "GIT_COMMITTER_EMAIL": "xa@b.cd",
        "GIT_AUTHOR_DATE": "2026-10-13T11:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T11:00:00+00:00",
    }
    (git_repo / "team1.txt").write_text("team1", encoding="utf-8")
    run_git(["add", "team1.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit by Teammate 1"], cwd=git_repo, env=env_teammate_1)

    # Teammate commit with dot matching anything: aXb.c (should NOT match)
    env_teammate_2 = {
        "GIT_AUTHOR_NAME": "Teammate 2",
        "GIT_AUTHOR_EMAIL": "aXb.c",
        "GIT_COMMITTER_NAME": "Teammate 2",
        "GIT_COMMITTER_EMAIL": "aXb.c",
        "GIT_AUTHOR_DATE": "2026-10-13T11:30:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T11:30:00+00:00",
    }
    (git_repo / "team2.txt").write_text("team2", encoding="utf-8")
    run_git(["add", "team2.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit by Teammate 2"], cwd=git_repo, env=env_teammate_2)

    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    commits = collect_commits(
        git_repo, since=since, until=until, author_emails=["a@b.c"], include_body=False
    )
    assert len(commits) == 1
    assert commits[0].subject == "Commit by Alice"


def test_collect_commits_all_branches_and_excludes_merges(git_repo: Path) -> None:
    """collect_commits scans all local branches and excludes merge commits."""
    email = "dev@example.com"
    env_dev = {
        "GIT_AUTHOR_NAME": "Dev",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Dev",
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": "2026-10-13T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T12:00:00+00:00",
    }

    # Commit on main branch
    (git_repo / "main_file.txt").write_text("main", encoding="utf-8")
    run_git(["add", "main_file.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit on main"], cwd=git_repo, env=env_dev)

    # Create and switch to feature branch
    run_git(["checkout", "-b", "feature-branch"], cwd=git_repo)
    env_feature = dict(env_dev)
    env_feature["GIT_AUTHOR_DATE"] = "2026-10-13T13:00:00+00:00"
    env_feature["GIT_COMMITTER_DATE"] = "2026-10-13T13:00:00+00:00"
    (git_repo / "feature_file.txt").write_text("feature", encoding="utf-8")
    run_git(["add", "feature_file.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit on feature"], cwd=git_repo, env=env_feature)

    # Switch back to main
    run_git(["checkout", "main"], cwd=git_repo)

    # Create merge commit
    env_merge = dict(env_dev)
    env_merge["GIT_AUTHOR_DATE"] = "2026-10-13T14:00:00+00:00"
    env_merge["GIT_COMMITTER_DATE"] = "2026-10-13T14:00:00+00:00"
    run_git(
        ["merge", "--no-ff", "feature-branch", "-m", "Merge feature-branch"],
        cwd=git_repo,
        env=env_merge,
    )

    # Check out detached or main: collect should include feature commit, but exclude merge
    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    commits = collect_commits(
        git_repo, since=since, until=until, author_emails=[email], include_body=False
    )
    subjects = [commit.subject for commit in commits]

    assert "Commit on main" in subjects
    assert "Commit on feature" in subjects
    assert "Merge feature-branch" not in subjects


def test_collect_commits_zero_commits_and_no_commits_today(tmp_path: Path) -> None:
    """collect_commits handles repos with zero commits and repos with no commits in window."""
    empty_repo = tmp_path / "zero_commits_repo"
    empty_repo.mkdir()
    run_git(["init"], cwd=empty_repo)

    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    # Repo with zero commits
    assert collect_commits(empty_repo, since, until, ["test@example.com"]) == []


def test_collect_commits_separator_chars_and_non_utf8(git_repo: Path) -> None:
    """collect_commits handles separator characters in messages and non-UTF-8 bytes safely."""
    email = "test@example.com"
    env = {
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": "2026-10-13T15:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T15:00:00+00:00",
    }

    # Commit with \x1f inside body
    body_with_separators = "Body line 1\x1fstill body\nSecond line"
    (git_repo / "sep.txt").write_text("sep", encoding="utf-8")
    run_git(["add", "sep.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Subject with sep", "-m", body_with_separators], cwd=git_repo, env=env)

    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    commits = collect_commits(
        git_repo, since=since, until=until, author_emails=[email], include_body=True
    )
    assert len(commits) >= 1
    sep_commit = [c for c in commits if c.subject == "Subject with sep"][0]
    assert "still body" in sep_commit.body


def test_collect_commits_author_with_plus_sign(git_repo: Path) -> None:
    """collect_commits matches author emails containing '+' such as GitHub noreply addresses."""
    plus_email = "12345+octo@users.noreply.github.com"
    env_plus = {
        "GIT_AUTHOR_NAME": "Octo",
        "GIT_AUTHOR_EMAIL": plus_email,
        "GIT_COMMITTER_NAME": "Octo",
        "GIT_COMMITTER_EMAIL": plus_email,
        "GIT_AUTHOR_DATE": "2026-10-13T10:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T10:00:00+00:00",
    }
    (git_repo / "plus_file.txt").write_text("plus", encoding="utf-8")
    run_git(["add", "plus_file.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit with plus address"], cwd=git_repo, env=env_plus)

    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    commits = collect_commits(
        git_repo, since=since, until=until, author_emails=[plus_email], include_body=False
    )
    assert len(commits) == 1
    assert commits[0].subject == "Commit with plus address"


def test_collect_commits_case_insensitive_and_multiple_ored(git_repo: Path) -> None:
    """collect_commits supports case-insensitive author matching and multiple ORed emails."""
    email_a = "alice@example.com"
    email_b = "bob@example.com"

    env_a = {
        "GIT_AUTHOR_NAME": "Alice",
        "GIT_AUTHOR_EMAIL": "Alice@Example.COM",  # Mixed case in commit
        "GIT_COMMITTER_NAME": "Alice",
        "GIT_COMMITTER_EMAIL": "Alice@Example.COM",
        "GIT_AUTHOR_DATE": "2026-10-13T10:10:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T10:10:00+00:00",
    }
    (git_repo / "a.txt").write_text("a", encoding="utf-8")
    run_git(["add", "a.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit from Alice"], cwd=git_repo, env=env_a)

    env_b = {
        "GIT_AUTHOR_NAME": "Bob",
        "GIT_AUTHOR_EMAIL": email_b,
        "GIT_COMMITTER_NAME": "Bob",
        "GIT_COMMITTER_EMAIL": email_b,
        "GIT_AUTHOR_DATE": "2026-10-13T10:20:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T10:20:00+00:00",
    }
    (git_repo / "b.txt").write_text("b", encoding="utf-8")
    run_git(["add", "b.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit from Bob"], cwd=git_repo, env=env_b)

    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    # Search with lowercase email_a and email_b
    commits = collect_commits(
        git_repo, since=since, until=until, author_emails=[email_a, email_b], include_body=False
    )
    subjects = [c.subject for c in commits]
    assert "Commit from Alice" in subjects
    assert "Commit from Bob" in subjects


def test_collect_commits_same_timestamp_oldest_first(git_repo: Path) -> None:
    """Commits created with the exact same timestamp must be ordered oldest-first."""
    email = "tester@example.com"
    same_time = "2026-10-13T12:00:00+00:00"
    env_same = {
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": same_time,
        "GIT_COMMITTER_DATE": same_time,
    }

    (git_repo / "tie1.txt").write_text("1", encoding="utf-8")
    run_git(["add", "tie1.txt"], cwd=git_repo)
    run_git(["commit", "-m", "First in tie"], cwd=git_repo, env=env_same)

    (git_repo / "tie2.txt").write_text("2", encoding="utf-8")
    run_git(["add", "tie2.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Second in tie"], cwd=git_repo, env=env_same)

    (git_repo / "tie3.txt").write_text("3", encoding="utf-8")
    run_git(["add", "tie3.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Third in tie"], cwd=git_repo, env=env_same)

    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    commits = collect_commits(
        git_repo, since=since, until=until, author_emails=[email], include_body=False
    )
    tie_subjects = [c.subject for c in commits if "in tie" in c.subject]
    assert tie_subjects == ["First in tie", "Second in tie", "Third in tie"]


def test_collect_commits_detached_head(git_repo: Path) -> None:
    """collect_commits collects commits from a detached HEAD state."""
    email = "tester@example.com"
    env = {
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_DATE": "2026-10-13T13:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-10-13T13:00:00+00:00",
    }
    run_git(["checkout", "--detach"], cwd=git_repo)
    (git_repo / "detached.txt").write_text("detached", encoding="utf-8")
    run_git(["add", "detached.txt"], cwd=git_repo)
    run_git(["commit", "-m", "Commit on detached HEAD"], cwd=git_repo, env=env)

    since = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)

    commits = collect_commits(
        git_repo, since=since, until=until, author_emails=[email], include_body=False
    )
    subjects = [c.subject for c in commits]
    assert "Commit on detached HEAD" in subjects

