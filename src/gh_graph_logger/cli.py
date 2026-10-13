"""Command line interface for gh-graph-logger."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from gh_graph_logger import __version__, draft
from gh_graph_logger.collector import (
    collect_commits,
    compute_window_start,
    parse_since,
    resolve_author_emails,
)
from gh_graph_logger.config import (
    Config,
    ConfigError,
    config_dir,
    config_path,
    load_config,
    save_config,
)
from gh_graph_logger.gitutil import GitError, run_git
from gh_graph_logger.guards import (
    GuardError,
    normalize_repo_url,
    require_git,
    require_git_repo,
    require_log_repo,
    require_remote_access,
)
from gh_graph_logger.project import resolve_project_name

# Exit code constants
OK: int = 0
ERROR: int = 1
# Note: Exit code 2 is reserved by argparse for CLI usage errors.
GUARD_FAILED: int = 3
ABORTED: int = 4


def format_status(success: bool) -> str:
    """Format check status with check/cross or [OK]/[FAIL] based on stdout encoding."""
    symbol = "✅" if success else "❌"
    fallback = "[OK]" if success else "[FAIL]"
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        symbol.encode(encoding)
        return symbol
    except UnicodeEncodeError:
        return fallback


def safe_print(text: str, file: Any = None) -> None:
    """Print text safely, replacing unencodable characters if needed."""
    target_file = file if file is not None else sys.stdout
    encoding = getattr(target_file, "encoding", None) or "utf-8"
    try:
        print(text, file=target_file)
    except UnicodeEncodeError:
        safe_encoded_text = text.encode(encoding, errors="replace").decode(encoding)
        print(safe_encoded_text, file=target_file)


def prompt(question: str, default: str | None = None) -> str:
    """Prompt the user for input with an optional default value."""
    if default:
        prompt_text = f"{question} [{default}]: "
    else:
        prompt_text = f"{question}: "

    try:
        response = input(prompt_text).strip()
    except EOFError:
        raise KeyboardInterrupt() from None

    if not response and default is not None:
        return default
    return response


def repo_name_from_url(repository_url: str) -> str:
    """Extract repository folder name from a git URL or local filesystem path."""
    cleaned_url = repository_url.strip().replace("\\", "/").rstrip("/")
    if cleaned_url.endswith(".git"):
        cleaned_url = cleaned_url[:-4].rstrip("/")

    last_slash_index = cleaned_url.rfind("/")
    last_colon_index = cleaned_url.rfind(":")
    split_index = max(last_slash_index, last_colon_index)
    if split_index != -1:
        extracted_name = cleaned_url[split_index + 1 :]
    else:
        extracted_name = cleaned_url
    extracted_name = extracted_name.strip()

    # Sanitize name: strip path traversal characters and fall back
    # to 'log-repo' if empty or '.' / '..'
    extracted_name = extracted_name.replace("..", "").strip("/\\ .")
    if not extracted_name or extracted_name in (".", ".."):
        return "log-repo"
    return extracted_name


def _resolve_and_validate_email(
    arguments: argparse.Namespace,
    existing_configuration: Config | None,
) -> str:
    """Prompt for, validate, and return the GitHub email address for log commits."""
    github_email = arguments.email
    if not github_email:
        default_email = existing_configuration.github_email if existing_configuration else None
        if not arguments.yes:
            github_email = prompt("GitHub email for log commits", default=default_email)
        elif default_email:
            github_email = default_email

    if not github_email or "@" not in github_email:
        raise GuardError(
            "GitHub email must contain '@'.",
            hint="Provide a valid GitHub email address.",
        )

    safe_print(
        f"Warning: Ensure '{github_email}' is verified on your GitHub account "
        "for contributions to count."
    )
    return github_email


def _configure_clone_identity(
    clone_path: Path,
    github_email: str,
    arguments: argparse.Namespace,
) -> None:
    """Set user.email and optionally user.name in the log repository clone."""
    run_git(["config", "--local", "--", "user.email", github_email], cwd=clone_path)

    if arguments.name:
        run_git(["config", "--local", "--", "user.name", arguments.name], cwd=clone_path)
    elif not arguments.yes:
        try:
            global_user_name = run_git(["config", "--global", "user.name"]).strip()
        except GitError:
            global_user_name = ""
        chosen_user_name = prompt(
            "Git user name for log commits", default=global_user_name or None
        )
        if chosen_user_name:
            run_git(["config", "--local", "--", "user.name", chosen_user_name], cwd=clone_path)
    else:
        try:
            global_user_name = run_git(["config", "--global", "user.name"]).strip()
            if global_user_name:
                run_git(["config", "--local", "--", "user.name", global_user_name], cwd=clone_path)
        except GitError:
            pass


def _resolve_branch_name(
    clone_path: Path,
    specified_branch: str | None,
    existing_configuration: Config | None,
) -> str:
    """Detect or fallback the target branch name for the log repository."""
    if specified_branch:
        return specified_branch

    try:
        symbolic_reference = run_git(
            ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=clone_path,
        ).strip()
        if symbolic_reference.startswith("origin/"):
            return symbolic_reference[7:]
        if symbolic_reference:
            return symbolic_reference
    except GitError:
        pass

    try:
        current_branch = run_git(["branch", "--show-current"], cwd=clone_path).strip()
        if current_branch:
            return current_branch
    except GitError:
        pass

    if existing_configuration and existing_configuration.branch:
        return existing_configuration.branch

    return "main"


def _stub(arguments: argparse.Namespace) -> int:
    """Stub handler for unreleased subcommands."""
    safe_print("not implemented yet")
    return ERROR


def handle_init(arguments: argparse.Namespace) -> int:
    """Initialize or configure the log repository clone."""
    existing_configuration = load_config()

    # Flow A: Adopting an existing clone via --path
    if arguments.path:
        specified_clone_path = Path(
            os.path.expandvars(os.path.expanduser(arguments.path))
        ).resolve()

        repository_url = arguments.url
        if not repository_url:
            if existing_configuration:
                repository_url = existing_configuration.log_repo_url
            elif not arguments.yes:
                repository_url = prompt("Log repository URL")

        if not repository_url:
            safe_print("Error: Log repository URL is required.", file=sys.stderr)
            return ERROR

        normalize_repo_url(repository_url)

        # Warn if remote access fails rather than blocking offline adoption
        try:
            require_remote_access(repository_url)
        except GuardError as exception:
            safe_print(
                f"Warning: Could not verify remote access ({exception.message}). "
                "Proceeding with local adoption."
            )

        if not specified_clone_path.exists():
            safe_print(
                f"Error: Specified path '{specified_clone_path}' does not exist.",
                file=sys.stderr,
            )
            return ERROR

        try:
            run_git(["rev-parse", "--show-toplevel"], cwd=specified_clone_path.parent)
            raise GuardError(
                f"Log repo clone at '{specified_clone_path}' cannot be nested "
                "inside another git repository."
            )
        except GitError:
            pass

        try:
            repository_top_level = Path(
                run_git(["rev-parse", "--show-toplevel"], cwd=specified_clone_path)
            ).resolve()
            if repository_top_level != specified_clone_path:
                safe_print(
                    f"Error: Specified path '{specified_clone_path}' "
                    "is not the root of a git repository.",
                    file=sys.stderr,
                )
                return ERROR

            origin_remote_url = run_git(
                ["remote", "get-url", "origin"], cwd=specified_clone_path
            ).strip()
            if normalize_repo_url(origin_remote_url) != normalize_repo_url(repository_url):
                safe_print(
                    f"Error: Existing clone origin URL '{origin_remote_url}' "
                    f"does not match expected URL '{repository_url}'.",
                    file=sys.stderr,
                )
                return ERROR
        except GitError as exception:
            safe_print(
                f"Error validating git clone at '{specified_clone_path}': {exception.message}",
                file=sys.stderr,
            )
            return ERROR

        github_email = _resolve_and_validate_email(arguments, existing_configuration)
        _configure_clone_identity(specified_clone_path, github_email, arguments)
        branch_name = _resolve_branch_name(
            specified_clone_path, arguments.branch, existing_configuration
        )

        new_configuration = Config(
            log_repo_url=repository_url,
            clone_path=str(specified_clone_path),
            branch=branch_name,
            github_email=github_email,
            last_push=(existing_configuration.last_push if existing_configuration else {}),
        )
        save_config(new_configuration)
        safe_print(
            f"{format_status(True)} Configured existing log repo clone at '{specified_clone_path}'."
        )
        return OK

    # Flow B: Normal init or --root (Strictly non-destructive)
    repository_url = arguments.url
    if not repository_url:
        default_url = existing_configuration.log_repo_url if existing_configuration else None
        if not arguments.yes:
            repository_url = prompt("Log repository URL", default=default_url)
        elif default_url:
            repository_url = default_url

    if not repository_url:
        safe_print("Error: Log repository URL is required.", file=sys.stderr)
        return ERROR

    # Validate repository URL syntax and verify remote access
    normalize_repo_url(repository_url)
    require_remote_access(repository_url)

    # Determine root directory
    default_root_directory = config_dir()
    if arguments.root:
        root_input = arguments.root
    elif not arguments.yes:
        root_input = prompt(
            "Root directory for the log repo", default=str(default_root_directory)
        )
    else:
        root_input = str(default_root_directory)

    root_directory = Path(os.path.expandvars(os.path.expanduser(root_input))).resolve()

    # Check whether nearest existing ancestor is inside a git repository
    nearest_ancestor = root_directory
    while not nearest_ancestor.exists() and nearest_ancestor != nearest_ancestor.parent:
        nearest_ancestor = nearest_ancestor.parent

    if nearest_ancestor.exists():
        try:
            work_tree_top_level = Path(
                run_git(["rev-parse", "--show-toplevel"], cwd=nearest_ancestor)
            ).resolve()
            raise GuardError(
                f"Root directory '{root_directory}' is inside a git repository "
                f"({work_tree_top_level}).",
                hint="Choose a root directory outside of any git repository using '--root <dir>'.",
            )
        except GitError:
            pass

    # Ask to create root directory if missing
    if not root_directory.exists():
        if not arguments.yes:
            confirmation = prompt(
                f"Directory '{root_directory}' does not exist. Create it? [Y/n]",
                default="y",
            )
            if confirmation.lower() not in ("y", "yes"):
                safe_print("Operation aborted by user.", file=sys.stderr)
                return ABORTED
        root_directory.mkdir(parents=True, exist_ok=True)

    repository_folder_name = repo_name_from_url(repository_url)
    if not repository_folder_name:
        repository_folder_name = "log-repo"

    target_clone_path = (root_directory / repository_folder_name).resolve()
    if target_clone_path.parent != root_directory:
        raise GuardError("Invalid repository URL resulting in path traversal.")

    github_email = _resolve_and_validate_email(arguments, existing_configuration)

    # Handle existing target directory (Strictly non-destructive)
    if target_clone_path.exists():
        is_matching_clone = False
        try:
            target_top_level = Path(
                run_git(["rev-parse", "--show-toplevel"], cwd=target_clone_path)
            ).resolve()
            if target_top_level == target_clone_path:
                origin_remote_url = run_git(
                    ["remote", "get-url", "origin"], cwd=target_clone_path
                ).strip()
                if normalize_repo_url(origin_remote_url) == normalize_repo_url(repository_url):
                    is_matching_clone = True
        except GitError:
            is_matching_clone = False

        if is_matching_clone:
            safe_print(f"Reusing existing clone at '{target_clone_path}'.")
        else:
            safe_print(
                f"Error: Directory '{target_clone_path}' already exists and "
                f"is not a clone of '{repository_url}'.",
                file=sys.stderr,
            )
            return ERROR
    else:
        safe_print(f"Cloning {repository_url} into {target_clone_path}...")
        clone_args = ["clone"]
        if arguments.branch:
            clone_args.extend(["--branch", arguments.branch])
        clone_args.extend(["--", repository_url, str(target_clone_path)])
        run_git(
            clone_args,
            env={"GIT_TERMINAL_PROMPT": "0"},
            timeout=300,
        )

    _configure_clone_identity(target_clone_path, github_email, arguments)
    branch_name = _resolve_branch_name(
        target_clone_path, arguments.branch, existing_configuration
    )

    new_configuration = Config(
        log_repo_url=repository_url,
        clone_path=str(target_clone_path),
        branch=branch_name,
        github_email=github_email,
        last_push=(existing_configuration.last_push if existing_configuration else {}),
    )
    save_config(new_configuration)
    safe_print(
        f"{format_status(True)} Successfully initialized log repo at '{target_clone_path}'."
    )
    return OK


def handle_check(arguments: argparse.Namespace) -> int:
    """Run all four guards and report verification status."""
    all_checks_passed = True

    # 1. require_git
    try:
        git_version = require_git()
        safe_print(f"{format_status(True)} Git executable ({git_version})")
    except GuardError as exception:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Git executable: {exception.message}")
        if exception.hint:
            safe_print(f"   Hint: {exception.hint}")

    # 2. require_git_repo
    try:
        current_work_repo = require_git_repo()
        safe_print(f"{format_status(True)} Inside git repository ({current_work_repo})")
    except GuardError as exception:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Inside git repository: {exception.message}")
        if exception.hint:
            safe_print(f"   Hint: {exception.hint}")

    # 3 & 4: Log repository clone and remote access
    try:
        loaded_configuration = load_config()
    except ConfigError as exception:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Log repository: configuration corrupt — {exception}")
        safe_print(
            f"{format_status(False)} Remote access: cannot verify due to corrupt configuration"
        )
        return GUARD_FAILED

    if loaded_configuration is None:
        all_checks_passed = False
        safe_print(f"{format_status(False)} Log repository: not configured — run ghlog init")
        safe_print(f"{format_status(False)} Remote access: log repository not configured")
    else:
        try:
            log_repo_path = require_log_repo(loaded_configuration)
            safe_print(f"{format_status(True)} Log repository clone ({log_repo_path})")
        except GuardError as exception:
            all_checks_passed = False
            safe_print(f"{format_status(False)} Log repository: {exception.message}")
            if exception.hint:
                safe_print(f"   Hint: {exception.hint}")

        try:
            normalize_repo_url(loaded_configuration.log_repo_url)
            require_remote_access(loaded_configuration.log_repo_url)
            safe_print(f"{format_status(True)} Remote access ({loaded_configuration.log_repo_url})")
        except GuardError as exception:
            all_checks_passed = False
            safe_print(f"{format_status(False)} Remote access: {exception.message}")
            if exception.hint:
                safe_print(f"   Hint: {exception.hint}")

    return OK if all_checks_passed else GUARD_FAILED


def handle_config(arguments: argparse.Namespace) -> int:
    """Display or manage configuration settings."""
    if not arguments.show:
        safe_print("Use 'ghlog config --show' to view configuration.", file=sys.stderr)
        return ERROR

    target_config_path = config_path()
    try:
        loaded_configuration = load_config()
    except ConfigError as exception:
        safe_print(f"Error reading configuration: {exception}", file=sys.stderr)
        return ERROR

    if loaded_configuration is None:
        safe_print(
            f"No configuration file found at '{target_config_path}'. Run `ghlog init`.",
            file=sys.stderr,
        )
        return ERROR

    safe_print(f"Configuration file: {target_config_path}")
    safe_print(f"  log_repo_url: {loaded_configuration.log_repo_url}")
    safe_print(f"  clone_path:   {loaded_configuration.clone_path}")
    safe_print(f"  branch:       {loaded_configuration.branch}")
    safe_print(f"  github_email: {loaded_configuration.github_email}")
    if loaded_configuration.last_push:
        safe_print("  last_push:")
        for project_name, timestamp in sorted(loaded_configuration.last_push.items()):
            safe_print(f"    {project_name}: {timestamp}")
    else:
        safe_print("  last_push:    (none)")

    return OK


def handle_collect(arguments: argparse.Namespace) -> int:
    """Collect commits from current repository and open a draft in git editor."""
    require_git()
    repo_root = require_git_repo()

    loaded_configuration = load_config()
    if loaded_configuration is None:
        raise GuardError(
            "gh-graph-logger is not configured.",
            hint="Run 'ghlog init' to configure your log repository.",
        )

    require_log_repo(loaded_configuration)

    since_override: datetime | None = None
    if arguments.since:
        try:
            since_override = parse_since(arguments.since)
        except ValueError as exception:
            safe_print(f"Error: {exception}", file=sys.stderr)
            return ERROR

    project_name = resolve_project_name(repo_root, override=arguments.project)
    now = datetime.now().astimezone()
    window_start = compute_window_start(
        project=project_name,
        last_push=loaded_configuration.last_push,
        now=now,
        since_override=since_override,
    )
    author_emails = resolve_author_emails(repo_root, override=arguments.author)

    target_draft_path = draft.draft_path(repo_root)
    reopen_existing_draft = False

    if target_draft_path.exists() and target_draft_path.stat().st_size > 0:
        existing_draft_text = target_draft_path.read_text(encoding="utf-8")
        existing_commits_count = draft.count_commit_lines(existing_draft_text)
        while True:
            choice = prompt(
                f"A draft already exists ({existing_commits_count} commits). "
                "[R]eopen it / [O]verwrite with fresh commits / [C]ancel",
                default="R",
            ).strip().lower()
            if choice in ("r", "reopen", ""):
                reopen_existing_draft = True
                updated_draft_text = draft.reappend_instructions_if_missing(existing_draft_text)
                target_draft_path.write_text(updated_draft_text, encoding="utf-8", newline="\n")
                break
            if choice in ("o", "overwrite"):
                reopen_existing_draft = False
                break
            if choice in ("c", "cancel"):
                safe_print("Aborted by user.")
                return ABORTED
            safe_print("Please enter 'r' to reopen, 'o' to overwrite, or 'c' to cancel.")

    if not reopen_existing_draft:
        commits = collect_commits(
            repo_root=repo_root,
            since=window_start,
            until=now,
            author_emails=author_emails,
            include_body=arguments.full,
        )
        if not commits:
            authors_display = ", ".join(author_emails)
            safe_print(
                f"No commits found since {window_start} for {authors_display}. "
                "Nothing to log."
            )
            return OK

        rendered_draft = draft.render_draft(
            project=project_name,
            commits=commits,
            generated_at=now,
            include_body=arguments.full,
        )
        target_draft_path.write_text(rendered_draft, encoding="utf-8", newline="\n")

    draft.open_editor(repo_root, target_draft_path)

    edited_content = target_draft_path.read_text(encoding="utf-8")
    cleaned_content = draft.strip_comments(edited_content)

    if not draft.has_commits(cleaned_content):
        target_draft_path.unlink(missing_ok=True)
        safe_print("Nothing to log - draft discarded.")
        return ABORTED

    target_draft_path.write_text(cleaned_content + "\n", encoding="utf-8", newline="\n")
    saved_commits_count = draft.count_commit_lines(cleaned_content)
    safe_print(
        f"Draft saved to {target_draft_path} with {saved_commits_count} commits. "
        "Publishing arrives in the next phase."
    )
    return OK


def build_parser() -> argparse.ArgumentParser:
    """Build and configure the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ghlog",
        description=(
            "Log your daily commits to your GitHub log repository to keep your "
            "contribution graph active."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="subcommand",
        title="subcommands",
        description="available commands",
    )

    # init
    parser_init = subparsers.add_parser(
        "init",
        help="Initialize or configure the log repo clone.",
    )
    root_group = parser_init.add_mutually_exclusive_group()
    root_group.add_argument("--root", type=str, help="Root directory for the log repo")
    root_group.add_argument("--path", type=str, help="Path to an existing log repo clone")
    parser_init.add_argument("--url", type=str, help="Git URL of the log repository")
    parser_init.add_argument("--email", type=str, help="GitHub email for log commits")
    parser_init.add_argument(
        "--branch",
        type=str,
        help="Branch name in the log repo (default: remote default or main)",
    )
    parser_init.add_argument("--name", type=str, help="Git user name for log commits")
    parser_init.add_argument(
        "--yes",
        action="store_true",
        help="Accept defaults and auto-create missing root directory",
    )
    parser_init.set_defaults(func=handle_init)

    # check
    parser_check = subparsers.add_parser(
        "check",
        help="Verify environment, git repo, and remote access.",
    )
    parser_check.set_defaults(func=handle_check)

    # collect
    parser_collect = subparsers.add_parser(
        "collect",
        help="Collect commits and create a draft.",
    )
    parser_collect.add_argument("--since", type=str, help="Collect commits since date/time")
    parser_collect.add_argument("--author", type=str, help="Author email(s) to filter by")
    parser_collect.add_argument("--full", action="store_true", help="Include full commit messages")
    parser_collect.add_argument("--project", type=str, help="Project name override")
    parser_collect.set_defaults(func=handle_collect)

    # push
    parser_push = subparsers.add_parser(
        "push",
        help="Push draft to the log repo.",
    )
    parser_push.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser_push.set_defaults(func=_stub)

    # discard
    parser_discard = subparsers.add_parser(
        "discard",
        help="Discard current draft.",
    )
    parser_discard.set_defaults(func=_stub)

    # config
    parser_config = subparsers.add_parser(
        "config",
        help="View or manage configuration.",
    )
    parser_config.add_argument("--show", action="store_true", help="Show current configuration")
    parser_config.set_defaults(func=handle_config)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the CLI. Returns exit code integer."""
    try:
        parser = build_parser()
        arguments = parser.parse_args(argv)

        if arguments.subcommand is None:
            parser.print_help()
            return ERROR

        handler = getattr(arguments, "func", None)
        if handler is not None:
            return handler(arguments)

        return ERROR
    except KeyboardInterrupt:
        safe_print("\nAborted by user.", file=sys.stderr)
        return ABORTED
    except GuardError as exception:
        error_message = f"Error: {exception.message}"
        if exception.hint:
            error_message += f"\nHint: {exception.hint}"
        safe_print(error_message, file=sys.stderr)
        return GUARD_FAILED
    except (ConfigError, GitError) as exception:
        safe_print(f"Error: {exception}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
