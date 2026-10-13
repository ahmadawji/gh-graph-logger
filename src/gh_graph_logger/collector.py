"""Commit collection and filtering logic for gh-graph-logger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gh_graph_logger.gitutil import GitError, run_git
from gh_graph_logger.guards import GuardError


@dataclass(frozen=True)
class CommitRecord:
    """Representation of an individual git commit collected for logging."""

    full_hash: str
    short_hash: str
    authored_at: datetime
    subject: str
    body: str


def parse_since(text: str) -> datetime:
    """Parse a date or datetime string for the --since option.

    Accepts:
        - 'YYYY-MM-DD' (interpreted as local midnight)
        - 'YYYY-MM-DD HH:MM' (in local timezone)
        - ISO-8601 datetime strings (e.g. 'YYYY-MM-DDTHH:MM:SS', with or without offset)

    Returns:
        A timezone-aware datetime instance in the local timezone (or preserving explicit offset).

    Raises:
        ValueError: If text does not match any accepted format.
    """
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("Invalid --since value: empty string provided.")

    local_timezone = datetime.now().astimezone().tzinfo

    # 1. Try 'YYYY-MM-DD' -> local midnight
    try:
        parsed_date = datetime.strptime(cleaned_text, "%Y-%m-%d")
        return parsed_date.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=local_timezone
        )
    except ValueError:
        pass

    # 2. Try 'YYYY-MM-DD HH:MM' -> local datetime
    try:
        parsed_datetime = datetime.strptime(cleaned_text, "%Y-%m-%d %H:%M")
        return parsed_datetime.replace(second=0, microsecond=0, tzinfo=local_timezone)
    except ValueError:
        pass

    # 3. Try standard ISO-8601 format
    try:
        parsed_iso = datetime.fromisoformat(cleaned_text)
        if parsed_iso.tzinfo is None:
            return parsed_iso.replace(tzinfo=local_timezone)
        return parsed_iso
    except ValueError:
        pass

    raise ValueError(
        f"Invalid date/time format for --since: '{text}'. "
        "Expected 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM', or an ISO-8601 datetime string."
    )


def compute_window_start(
    project: str,
    last_push: dict[str, str],
    now: datetime,
    since_override: datetime | None = None,
) -> datetime:
    """Compute the starting timestamp of the commit collection window.

    If since_override is provided, returns since_override directly.
    Otherwise, returns max(local midnight today, last_push timestamp for project).
    All comparisons use timezone-aware local time.

    Args:
        project: Slugified project name.
        last_push: Dictionary mapping project names to ISO-formatted push timestamps.
        now: Current timezone-aware datetime.
        since_override: Optional explicit start datetime from --since.

    Returns:
        Timezone-aware datetime representing the start of the collection window.
    """
    if since_override is not None:
        return since_override

    target_timezone = now.tzinfo or datetime.now().astimezone().tzinfo
    local_midnight = now.astimezone(target_timezone).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    raw_last_push = last_push.get(project)
    if raw_last_push:
        try:
            parsed_push = datetime.fromisoformat(raw_last_push)
            if parsed_push.tzinfo is None:
                parsed_push = parsed_push.replace(tzinfo=target_timezone)
            else:
                parsed_push = parsed_push.astimezone(target_timezone)
            return max(local_midnight, parsed_push)
        except (ValueError, TypeError):
            # Unparseable timestamps are safely ignored
            pass

    return local_midnight


def resolve_author_emails(
    repo_root: Path,
    override: str | None = None,
) -> list[str]:
    """Resolve the list of author emails to filter commits by.

    Priority order:
    1. CLI override string (comma-separated).
    2. Local repo git config: `git config --local --get ghlog.author` (comma-separated).
    3. Repo user email: `git config user.email`.

    Args:
        repo_root: Root directory of the working git repository.
        override: Optional comma-separated author emails from CLI.

    Returns:
        A list of trimmed email address strings.

    Raises:
        GuardError: If no author email can be found.
    """
    if override is not None:
        emails = [email.strip() for email in override.split(",") if email.strip()]
        if emails:
            return emails

    try:
        stored_authors = run_git(
            ["config", "--local", "--get", "ghlog.author"],
            cwd=repo_root,
            check=False,
        ).strip()
        if stored_authors:
            emails = [email.strip() for email in stored_authors.split(",") if email.strip()]
            if emails:
                return emails
    except GitError:
        pass

    try:
        user_email = run_git(["config", "user.email"], cwd=repo_root, check=False).strip()
        if user_email:
            return [user_email]
    except GitError:
        pass

    raise GuardError(
        "No author email configured for commits.",
        hint="Configure 'git config user.email <email>', set 'git config ghlog.author', "
        "or pass '--author <email>'.",
    )


def collect_commits(
    repo_root: Path,
    since: datetime,
    until: datetime,
    author_emails: list[str],
    include_body: bool = False,
) -> list[CommitRecord]:
    """Collect commits matching author and date criteria from all local branches.

    Note:
        Git's `--since` filter operates on the committer date, not author date.
        This function uses `--since` and `--until` bounds as git options, and
        sorts results ascending by `authored_at`.
        Merge commits are excluded via `--no-merges`.

    Args:
        repo_root: Path to the working git repository root.
        since: Earliest commit timestamp bound.
        until: Latest commit timestamp bound (typically 'now').
        author_emails: List of author emails to match.
        include_body: Whether to populate the commit body in CommitRecord.

    Returns:
        List of CommitRecord objects deduplicated by commit hash and sorted
        chronologically ascending by authored_at.
    """
    command_arguments = [
        "log",
        "--branches",
        "HEAD",
        "--no-merges",
        "--reverse",
        f"--since={since.isoformat()}",
        f"--until={until.isoformat()}",
        "--fixed-strings",
        "--regexp-ignore-case",
        "--date=iso-strict",
        "--pretty=format:%H%x1f%aI%x1f%s%x1f%b%x1e",
    ]

    for email in author_emails:
        command_arguments.append(f"--author=<{email}>")

    try:
        raw_output = run_git(command_arguments, cwd=repo_root)
    except GitError as exception:
        # Repositories with no commits or missing HEAD
        error_text = (exception.stderr + " " + exception.message).lower()
        if (
            "does not have any commits yet" in error_text
            or "bad default revision" in error_text
            or "unknown revision or path not in the working tree" in error_text
        ):
            return []
        raise

    if not raw_output.strip():
        return []

    collected_records: list[CommitRecord] = []
    seen_hashes: set[str] = set()

    for raw_record in raw_output.split("\x1e"):
        cleaned_record = raw_record.strip("\r\n")
        if not cleaned_record:
            continue

        parts = cleaned_record.split("\x1f", 3)
        if len(parts) < 3:
            continue

        full_hash = parts[0].strip()
        if not full_hash or full_hash in seen_hashes:
            continue

        seen_hashes.add(full_hash)
        short_hash = full_hash[:7]

        authored_at_string = parts[1].strip()
        try:
            authored_at = datetime.fromisoformat(authored_at_string)
        except ValueError:
            continue

        subject = parts[2].strip()
        body = parts[3].strip() if (include_body and len(parts) > 3) else ""

        collected_records.append(
            CommitRecord(
                full_hash=full_hash,
                short_hash=short_hash,
                authored_at=authored_at,
                subject=subject,
                body=body,
            )
        )

    collected_records.sort(key=lambda record: record.authored_at)
    return collected_records
