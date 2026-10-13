"""Handler and helpers for `ghlog init` subcommand."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from gh_graph_logger.config import Config, config_dir, load_config, save_config
from gh_graph_logger.console import format_status, prompt, safe_print
from gh_graph_logger.exitcodes import ABORTED, ERROR, OK
from gh_graph_logger.gitutil import GitError, run_git
from gh_graph_logger.guards import (
    GuardError,
    normalize_repo_url,
    require_remote_access,
)


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

    from gh_graph_logger import cli

    name_resolver = getattr(cli, "repo_name_from_url", repo_name_from_url)
    repository_folder_name = name_resolver(repository_url)
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
