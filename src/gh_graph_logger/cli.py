"""Command line interface for gh-graph-logger."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gh_graph_logger import __version__
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
    return extracted_name.strip()


def _handle_remove_readonly(action: Any, file_path: str, exception_info: Any) -> None:
    """Error handler for shutil.rmtree to remove read-only attributes on Windows."""
    import stat

    try:
        os.chmod(file_path, stat.S_IWRITE)
        action(file_path)
    except Exception:
        pass


def _stub(arguments: argparse.Namespace) -> int:
    """Stub handler for unreleased subcommands."""
    safe_print("not implemented yet")
    return ERROR


def handle_init(arguments: argparse.Namespace) -> int:
    """Initialize or configure the log repository clone."""
    # Flow A: Adopting an existing clone via --path
    if arguments.path:
        specified_clone_path = Path(
            os.path.expandvars(os.path.expanduser(arguments.path))
        ).resolve()

        existing_configuration = load_config()
        repository_url = arguments.url
        if not repository_url:
            if existing_configuration:
                repository_url = existing_configuration.log_repo_url
            elif not arguments.yes:
                repository_url = prompt("Log repository URL")

        if not repository_url:
            safe_print("Error: Log repository URL is required.", file=sys.stderr)
            return ERROR

        require_remote_access(repository_url)

        if not specified_clone_path.exists():
            safe_print(
                f"Error: Specified path '{specified_clone_path}' does not exist.",
                file=sys.stderr,
            )
            return ERROR

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

        branch_name = arguments.branch
        if not branch_name:
            try:
                branch_name = run_git(
                    ["branch", "--show-current"], cwd=specified_clone_path
                ).strip()
            except GitError:
                branch_name = ""
            if not branch_name:
                branch_name = existing_configuration.branch if existing_configuration else "main"

        run_git(["config", "user.email", github_email], cwd=specified_clone_path)
        if arguments.name:
            run_git(["config", "user.name", arguments.name], cwd=specified_clone_path)

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

    # Flow B: Normal init or --root or --reclone
    existing_configuration = load_config()
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

    # Verify remote access before creating directories
    require_remote_access(repository_url)

    # Determine root directory
    default_root_directory = config_dir()
    if arguments.root:
        root_input = arguments.root
    elif not arguments.yes:
        root_input = prompt("Root directory for the log repo", default=str(default_root_directory))
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
                hint="Choose a root directory outside of any git repository.",
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

    # Handle existing target directory
    if target_clone_path.exists():
        if arguments.reclone:
            has_unpushed_commits = False
            if (target_clone_path / ".git").exists():
                try:
                    unpushed_count_output = run_git(
                        ["rev-list", "--count", "@{u}..HEAD"], cwd=target_clone_path
                    ).strip()
                    if unpushed_count_output and int(unpushed_count_output) > 0:
                        has_unpushed_commits = True
                except GitError:
                    has_unpushed_commits = True

            if has_unpushed_commits:
                safe_print(
                    f"Warning: Existing clone at '{target_clone_path}' has unpushed "
                    "commits that will be lost.",
                    file=sys.stderr,
                )
                if not arguments.yes:
                    confirmation = prompt(
                        "Re-cloning will delete all unpushed commits. "
                        "Are you sure you want to proceed? [y/N]",
                        default="n",
                    )
                    if confirmation.lower() not in ("y", "yes"):
                        safe_print("Operation aborted by user.", file=sys.stderr)
                        return ABORTED

            shutil.rmtree(target_clone_path, onerror=_handle_remove_readonly)
        else:
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

    # Clone repository if target does not exist
    if not target_clone_path.exists():
        safe_print(f"Cloning {repository_url} into {target_clone_path}...")
        run_git(
            ["clone", repository_url, str(target_clone_path)],
            env={"GIT_TERMINAL_PROMPT": "0"},
            timeout=300,
        )

    # Detect branch
    branch_name = arguments.branch
    if not branch_name:
        try:
            symbolic_reference = run_git(
                ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                cwd=target_clone_path,
            ).strip()
            if symbolic_reference.startswith("origin/"):
                branch_name = symbolic_reference[7:]
            else:
                branch_name = symbolic_reference
        except GitError:
            try:
                branch_name = run_git(["branch", "--show-current"], cwd=target_clone_path).strip()
            except GitError:
                branch_name = ""
        if not branch_name:
            branch_name = "main"

    # Determine email
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

    # Configure git identity in log repo clone
    run_git(["config", "user.email", github_email], cwd=target_clone_path)

    if arguments.name:
        run_git(["config", "user.name", arguments.name], cwd=target_clone_path)
    elif not arguments.yes:
        try:
            global_user_name = run_git(["config", "--global", "user.name"]).strip()
        except GitError:
            global_user_name = ""
        chosen_user_name = prompt("Git user name for log commits", default=global_user_name or None)
        if chosen_user_name:
            run_git(["config", "user.name", chosen_user_name], cwd=target_clone_path)
    else:
        try:
            global_user_name = run_git(["config", "--global", "user.name"]).strip()
            if global_user_name:
                run_git(["config", "user.name", global_user_name], cwd=target_clone_path)
        except GitError:
            pass

    # Save configuration
    new_configuration = Config(
        log_repo_url=repository_url,
        clone_path=str(target_clone_path),
        branch=branch_name,
        github_email=github_email,
        last_push=(existing_configuration.last_push if existing_configuration else {}),
    )
    save_config(new_configuration)
    safe_print(f"{format_status(True)} Successfully initialized log repo at '{target_clone_path}'.")
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
    parser_init.add_argument("--root", type=str, help="Root directory for the log repo")
    parser_init.add_argument("--path", type=str, help="Path to an existing log repo clone")
    parser_init.add_argument(
        "--reclone", action="store_true", help="Re-clone the log repo from scratch"
    )
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
    parser_collect.set_defaults(func=_stub)

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
