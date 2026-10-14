"""Command line interface for gh-graph-logger."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

from gh_graph_logger import __version__
from gh_graph_logger.config import (
    Config,
    config_dir,
    config_path,
    load_config,
    save_config,
)
from gh_graph_logger.gitutil import GitError, GitNotFoundError, run_git

# Exit code constants
OK: int = 0
ERROR: int = 1
GUARD_FAILED: int = 3
ABORTED: int = 4

__all__ = [
    "ABORTED",
    "ERROR",
    "GUARD_FAILED",
    "OK",
    "_configure_clone_identity",
    "build_parser",
    "format_status",
    "get_editor",
    "handle_check",
    "handle_config",
    "handle_daily",
    "handle_init",
    "main",
    "normalize_url",
    "open_editor",
    "repo_name_from_url",
    "safe_print",
    "slugify",
]


def safe_print(message: str = "", file: TextIO | None = None) -> None:
    """Print message handling possible encoding errors on restricted consoles."""
    target_file = file or sys.stdout
    try:
        print(message, file=target_file)
    except UnicodeEncodeError:
        encoding = getattr(target_file, "encoding", "ascii") or "ascii"
        clean = message.encode(encoding, errors="replace").decode(encoding)
        print(clean, file=target_file)


def format_status(ok: bool) -> str:
    """Format a status boolean as [OK] / [FAIL] or unicode check/cross."""
    stream = sys.stdout
    encoding = getattr(stream, "encoding", "") or "utf-8"
    try:
        "✅".encode(encoding)
        return "✅" if ok else "❌"
    except (UnicodeEncodeError, LookupError):
        return "[OK]" if ok else "[FAIL]"


def is_git_repo(cwd: Path | None = None) -> bool:
    """Check if the given directory is inside a Git repository."""
    try:
        run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
        return True
    except (GitError, GitNotFoundError):
        return False


def is_inside_git_repo(path: Path) -> bool:
    """Check if path or any of its existing ancestors is inside a git repo."""
    curr = path.resolve()
    while not curr.exists() and curr.parent != curr:
        curr = curr.parent
    try:
        run_git(["rev-parse", "--show-toplevel"], cwd=curr)
        return True
    except (GitError, GitNotFoundError):
        return False


def get_repo_root(cwd: Path | None = None) -> Path:
    """Return the root path of the Git repository."""
    out = run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(out).resolve()


def repo_name_from_url(url: str) -> str:
    """Extract a safe repository directory name from a git URL."""
    cleaned = url.replace("\\", "/").rstrip("/ ")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    name = cleaned.split("/")[-1].split(":")[-1].strip()
    if not name or name in (".", ".."):
        return "log-repo"
    return name


def slugify(name: str) -> str:
    """Convert a project or repository name to a clean alphanumeric slug."""
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", name.replace("_", "-")).strip("-").lower()
    slug = re.sub(r"-+", "-", slug)
    return slug or "project"


def normalize_url(url: str) -> str:
    """Normalize a git URL or local path for comparison."""
    cleaned = url.strip().replace("\\", "/").rstrip("/")
    if cleaned.lower().endswith(".git"):
        cleaned = cleaned[:-4]
    for prefix in ("git@github.com:", "ssh://git@github.com/", "http://github.com/"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = "https://github.com/" + cleaned[len(prefix) :]
            break
    return cleaned.lower()


def get_editor() -> list[str]:
    """Determine the editor command to use."""
    editor = os.environ.get("GIT_EDITOR") or os.environ.get("EDITOR")
    if not editor:
        try:
            core_editor = run_git(["config", "core.editor"], check=False).strip()
            if core_editor:
                editor = core_editor
        except Exception:
            pass
    if not editor:
        editor = "notepad" if os.name == "nt" else "vim"
    tokens = shlex.split(editor, posix=(os.name != "nt"))
    return [token.strip("\"'") for token in tokens]


def open_editor(file_path: Path) -> None:
    """Open the file in the user's preferred editor."""
    cmd = [*get_editor(), str(file_path)]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Editor executable not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Editor returned non-zero exit code: {exc.returncode}") from exc


def _configure_clone_identity(repo_dir: Path, email: str, args: argparse.Namespace) -> None:
    """Configure local git user identity inside the clone."""
    run_git(["config", "--local", "--", "user.email", email], cwd=repo_dir)
    name = getattr(args, "name", None)
    if name:
        run_git(["config", "--local", "--", "user.name", name], cwd=repo_dir)
    else:
        try:
            global_name = run_git(["config", "user.name"], cwd=repo_dir).strip()
            if global_name:
                run_git(["config", "--local", "--", "user.name", global_name], cwd=repo_dir)
        except Exception:
            pass


def handle_init(args: argparse.Namespace) -> int:
    """Initialize or configure the log repo clone."""
    url = args.url or ""
    if url.startswith("-"):
        safe_print("Error: URLs starting with '-' are not permitted.", file=sys.stderr)
        return GUARD_FAILED
    if url.lower().startswith(("ext::", "fd::")):
        safe_print("Error: Dangerous or unsupported git protocol in URL.", file=sys.stderr)
        return GUARD_FAILED

    if not url and not args.path:
        if args.yes:
            safe_print("Error: --url is required in non-interactive mode.", file=sys.stderr)
            return ERROR
        url = input("Log repository git URL: ").strip()
        if not url:
            safe_print("Error: Log repository URL cannot be empty.", file=sys.stderr)
            return ERROR
        if url.startswith("-"):
            safe_print("Error: URLs starting with '-' are not permitted.", file=sys.stderr)
            return GUARD_FAILED
        if url.lower().startswith(("ext::", "fd::")):
            safe_print("Error: Dangerous or unsupported git protocol in URL.", file=sys.stderr)
            return GUARD_FAILED

    email = args.email or ""
    if not email:
        default_email = ""
        try:
            default_email = run_git(["config", "user.email"], check=False).strip()
        except Exception:
            pass
        if args.yes:
            email = default_email
        else:
            prompt_str = f"GitHub email [{default_email}]: " if default_email else "GitHub email: "
            entered = input(prompt_str).strip()
            email = entered or default_email

    if not email or "@" not in email:
        safe_print("Error: Email must contain '@'.", file=sys.stderr)
        return GUARD_FAILED

    if args.path:
        clone_path = Path(args.path).expanduser().resolve()
        if not clone_path.exists() or not is_git_repo(clone_path):
            safe_print(
                f"Error: Path '{clone_path}' is not an existing Git repository.",
                file=sys.stderr,
            )
            return ERROR
        if get_repo_root(clone_path) != clone_path:
            safe_print(
                f"Error: Specified path '{clone_path}' is not the root of a git repository.",
                file=sys.stderr,
            )
            return ERROR
        if is_inside_git_repo(clone_path.parent):
            safe_print(
                "Error: Clone path cannot be nested inside another git repository.",
                file=sys.stderr,
            )
            return GUARD_FAILED
        if not url:
            try:
                url = run_git(["remote", "get-url", "origin"], cwd=clone_path).strip()
            except GitError:
                url = ""
    else:
        root_dir = Path(args.root).expanduser().resolve() if args.root else config_dir()
        if is_inside_git_repo(root_dir):
            safe_print(
                "Error: Root directory cannot be inside an existing git repository.",
                file=sys.stderr,
            )
            return GUARD_FAILED

        repo_name = repo_name_from_url(url)
        target_dir = (root_dir / repo_name).resolve()
        try:
            target_dir.relative_to(root_dir.resolve())
        except ValueError:
            safe_print(
                "Error: Invalid repository URL resulting in path traversal.",
                file=sys.stderr,
            )
            return GUARD_FAILED

        if target_dir.exists():
            if is_git_repo(target_dir):
                origin = run_git(["remote", "get-url", "origin"], cwd=target_dir).strip()
                if normalize_url(origin) != normalize_url(url):
                    msg = (
                        f"Error: Target directory '{target_dir}' already exists "
                        f"and is not a clone of '{url}'."
                    )
                    safe_print(msg, file=sys.stderr)
                    return ERROR
                safe_print(f"Reusing existing clone at '{target_dir}'.")
                clone_path = target_dir
            else:
                msg = (
                    f"Error: Target directory '{target_dir}' already exists "
                    f"and is not a clone of '{url}'."
                )
                safe_print(msg, file=sys.stderr)
                return ERROR
        else:
            root_dir.mkdir(parents=True, exist_ok=True)
            safe_print(f"Cloning '{url}' into '{target_dir}'...")
            clone_cmd = ["clone"]
            if getattr(args, "branch", None):
                clone_cmd.extend(["-b", args.branch])
            clone_cmd.extend(["--", url, str(target_dir)])
            try:
                run_git(clone_cmd)
            except GitError as exc:
                safe_print(f"Error cloning repository: {exc}", file=sys.stderr)
                return ERROR
            clone_path = target_dir

    _configure_clone_identity(clone_path, email, args)

    branch = getattr(args, "branch", None)
    if not branch:
        try:
            branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=clone_path).strip()
        except GitError:
            branch = "main"

    existing_config = load_config()
    last_push = existing_config.last_push if existing_config else {}

    cfg = Config(
        log_repo_url=url,
        clone_path=str(clone_path),
        branch=branch or "main",
        github_email=email,
        last_push=last_push,
    )
    save_config(cfg)
    safe_print(f"Initialized ghlog successfully! Log clone at '{clone_path}'.")
    return OK


def handle_check(args: argparse.Namespace) -> int:
    """Verify git environment, current repository, and log repo clone."""
    all_ok = True

    # 1. Git executable
    try:
        git_ver = run_git(["--version"]).strip()
        safe_print(f"{format_status(True)} Git executable: {git_ver}")
    except Exception as exc:
        safe_print(f"{format_status(False)} Git executable: {exc}", file=sys.stderr)
        all_ok = False

    # 2. Inside git repository
    try:
        repo_root = get_repo_root()
        safe_print(f"{format_status(True)} Inside git repository: {repo_root}")
    except Exception:
        safe_print(
            f"{format_status(False)} Inside git repository: Not inside a git repository",
            file=sys.stderr,
        )
        all_ok = False

    # 3. Config and clone
    cfg = load_config()
    if cfg is None:
        safe_print(
            f"{format_status(False)} Log repository clone: not configured - run ghlog init",
            file=sys.stderr,
        )
        all_ok = False
    else:
        clone_path = Path(cfg.clone_path)
        if clone_path.exists() and is_git_repo(clone_path):
            safe_print(f"{format_status(True)} Log repository clone: {clone_path}")
            # Check remote access
            try:
                run_git(
                    ["ls-remote", "--exit-code", "--", cfg.log_repo_url, "HEAD"],
                    env={"GIT_TERMINAL_PROMPT": "0"},
                    timeout=15,
                )
                safe_print(f"{format_status(True)} Remote access: {cfg.log_repo_url}")
            except GitError as exc:
                if exc.returncode == 2:
                    safe_print(
                        f"{format_status(True)} Remote access: {cfg.log_repo_url} "
                        "(empty repository)"
                    )
                else:
                    msg = f"{format_status(False)} Remote access: unreachable"
                    safe_print(msg, file=sys.stderr)
                    all_ok = False
            except Exception:
                safe_print(f"{format_status(False)} Remote access: unreachable", file=sys.stderr)
                all_ok = False
        else:
            safe_print(
                f"{format_status(False)} Log repository clone: not found at {clone_path}",
                file=sys.stderr,
            )
            all_ok = False

    return OK if all_ok else GUARD_FAILED


def handle_config(args: argparse.Namespace) -> int:
    """Display configuration settings."""
    if not getattr(args, "show", False):
        safe_print("Error: Use 'ghlog config --show' to view configuration.", file=sys.stderr)
        return ERROR

    cfg = load_config()
    if cfg is None:
        safe_print("No configuration file found. Run 'ghlog init' first.", file=sys.stderr)
        return ERROR

    safe_print(f"Configuration file: {config_path()}")
    safe_print(f"Log repo URL:       {cfg.log_repo_url}")
    safe_print(f"Clone path:         {cfg.clone_path}")
    safe_print(f"Branch:             {cfg.branch}")
    safe_print(f"GitHub email:       {cfg.github_email}")
    if cfg.last_push:
        safe_print("Last push history:")
        for proj, timestamp in cfg.last_push.items():
            safe_print(f"  {proj}: {timestamp}")
    return OK


def handle_daily(args: argparse.Namespace) -> int:
    """Core daily flow: fetch commits, edit draft, confirm, and push to log repository."""
    if not is_git_repo():
        safe_print("Error: Current directory is not a Git repository.", file=sys.stderr)
        return GUARD_FAILED

    repo_root = get_repo_root()
    cfg = load_config()
    if cfg is None:
        safe_print("Error: ghlog is not configured. Run 'ghlog init' first.", file=sys.stderr)
        return GUARD_FAILED

    clone_path = Path(cfg.clone_path)
    if not clone_path.exists() or not is_git_repo(clone_path):
        safe_print(
            f"Error: Log repository clone not found at '{clone_path}'. Run 'ghlog init'.",
            file=sys.stderr,
        )
        return GUARD_FAILED

    project = slugify(getattr(args, "project", None) or repo_root.name)
    author = getattr(args, "author", None)
    if not author:
        try:
            author = run_git(["config", "user.email"], cwd=repo_root).strip()
        except Exception:
            author = cfg.github_email

    since = getattr(args, "since", None) or cfg.last_push.get(project) or "midnight"

    git_cmd = [
        "log",
        "--reverse",
        "--no-merges",
        f"--since={since}",
        "--pretty=format:- %h %s",
    ]
    if author:
        git_cmd.append(f"--author={author}")

    try:
        raw_log = run_git(git_cmd, cwd=repo_root).strip()
    except GitError as exc:
        safe_print(f"Error querying git log: {exc}", file=sys.stderr)
        return ERROR

    commits = [line.strip() for line in raw_log.splitlines() if line.strip().startswith("- ")]
    if not commits:
        safe_print(f"No commits found for '{project}' since '{since}'. Nothing to log.")
        return OK

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    draft_header = [
        f"# Commits for {project} - {now_str}",
        "# Lines starting with '#' are comments and will be ignored.",
        "# Delete lines you do not want to log. Save an empty file to abort.",
        "",
    ]
    draft_text = "\n".join(draft_header) + "\n" + "\n".join(commits) + "\n"

    try:
        git_dir_str = run_git(["rev-parse", "--git-dir"], cwd=repo_root).strip()
        git_dir = Path(git_dir_str)
        draft_dir = git_dir if git_dir.is_absolute() else (repo_root / git_dir).resolve()
    except Exception:
        draft_dir = repo_root
    draft_file = draft_dir / "ghlog_draft.md"

    try:
        draft_file.write_text(draft_text, encoding="utf-8")
        open_editor(draft_file)
        edited_text = draft_file.read_text(encoding="utf-8")
    finally:
        if draft_file.exists():
            draft_file.unlink(missing_ok=True)

    kept_commits = [
        line.strip()
        for line in edited_text.splitlines()
        if not line.strip().startswith("#") and line.strip().startswith("- ")
    ]

    if not kept_commits:
        safe_print("No commits left in draft. Cancelled.")
        return OK

    count = len(kept_commits)
    if not getattr(args, "yes", False):
        prompt_msg = f"Push {count} commit(s) for '{project}' to log repo? [y/N]: "
        confirm = input(prompt_msg).strip().lower()
        if confirm not in ("y", "yes"):
            safe_print("Aborted. Draft discarded.")
            return ABORTED

    # Sync clone before writing
    run_git(["pull", "--rebase"], cwd=clone_path, check=False)

    # Write log file in clone
    date_file = now.strftime("%Y-%m-%d")
    project_dir = clone_path / project
    project_dir.mkdir(parents=True, exist_ok=True)
    target_file = project_dir / f"{date_file}.md"
    entry_body = f"## {now_str}\n\n" + "\n".join(kept_commits) + "\n"

    if target_file.exists():
        existing = target_file.read_text(encoding="utf-8")
        target_file.write_text(existing.rstrip() + "\n\n" + entry_body, encoding="utf-8")
    else:
        target_file.write_text(f"# {project}\n\n" + entry_body, encoding="utf-8")

    # Git operations in clone
    try:
        run_git(["add", "."], cwd=clone_path)
        commit_msg = f"log: {project} {now.strftime('%Y-%m-%d %H:%M:%S')}"
        # Ensure user identity in clone repo if not already configured
        existing_email = run_git(["config", "user.email"], cwd=clone_path, check=False).strip()
        committer_email = cfg.github_email or author or "logger@local"
        if not existing_email:
            run_git(["config", "user.email", committer_email], cwd=clone_path)
        existing_name = run_git(["config", "user.name"], cwd=clone_path, check=False).strip()
        if not existing_name:
            committer_name = committer_email.split("@")[0] if "@" in committer_email else "ghlog"
            run_git(["config", "user.name", committer_name], cwd=clone_path)

        run_git(["commit", "-m", commit_msg], cwd=clone_path)
    except GitError as exc:
        safe_print(f"Error updating log repository: {exc}", file=sys.stderr)
        return ERROR

    try:
        run_git(["push"], cwd=clone_path, check=True)
    except GitError as exc:
        safe_print(
            f"Warning: Commit created locally in log clone, but push failed: {exc}\n"
            "The log commit is preserved locally and will be retried on your next push.",
            file=sys.stderr,
        )
        return ERROR

    cfg.last_push[project] = now.isoformat()
    save_config(cfg)
    safe_print(f"Successfully logged {count} commit(s) for '{project}' to {cfg.log_repo_url}!")
    return OK


def build_parser() -> argparse.ArgumentParser:
    """Build and configure the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ghlog",
        description="Log your daily commits to your GitHub log repository.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Collect commits since date/time (default: midnight)",
    )
    parser.add_argument("--author", type=str, help="Author email(s) to filter by")
    parser.add_argument(
        "--project",
        type=str,
        help="Project name override (default: repository folder name)",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    subparsers = parser.add_subparsers(
        dest="subcommand",
        title="subcommands",
    )

    # init
    parser_init = subparsers.add_parser("init", help="Initialize or configure the log repo clone.")
    root_group = parser_init.add_mutually_exclusive_group()
    root_group.add_argument("--root", type=str, help="Root directory for the log repo clone")
    root_group.add_argument("--path", type=str, help="Path to an existing log repo clone")
    parser_init.add_argument("--url", type=str, help="Git URL of the log repository")
    parser_init.add_argument("--email", type=str, help="GitHub email for log commits")
    parser_init.add_argument("--branch", type=str, help="Branch name in the log repo")
    parser_init.add_argument("--name", type=str, help="Git user name for log commits")
    parser_init.add_argument("--yes", "-y", action="store_true", help="Accept defaults")

    # check
    subparsers.add_parser("check", help="Verify environment, git repo, and remote access.")

    # config
    parser_config = subparsers.add_parser("config", help="View configuration.")
    parser_config.add_argument("--show", action="store_true", help="Show current configuration")

    # collect alias for daily flow
    parser_collect = subparsers.add_parser("collect", help="Alias for daily commit logging.")
    parser_collect.add_argument("--since", type=str, help="Collect commits since date/time")
    parser_collect.add_argument("--author", type=str, help="Author email(s) to filter by")
    parser_collect.add_argument("--project", type=str, help="Project name override")
    parser_collect.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the CLI. Returns exit code integer."""
    try:
        parser = build_parser()
        args = parser.parse_args(argv)

        if args.subcommand is None or args.subcommand == "collect":
            return handle_daily(args)
        elif args.subcommand == "init":
            return handle_init(args)
        elif args.subcommand == "check":
            return handle_check(args)
        elif args.subcommand == "config":
            return handle_config(args)
        else:
            safe_print(f"Unknown subcommand: {args.subcommand}", file=sys.stderr)
            return ERROR
    except KeyboardInterrupt:
        safe_print("\nAborted by user.", file=sys.stderr)
        return ABORTED
    except Exception as exc:
        safe_print(f"Error: {exc}", file=sys.stderr)
        return ERROR
