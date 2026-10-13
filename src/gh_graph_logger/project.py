"""Project name resolution and slugification for gh-graph-logger."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from gh_graph_logger.gitutil import GitError, run_git


def slugify(name: str) -> str:
    """Convert a project or repository name into a safe filesystem and URL slug.

    Transforms to lowercase, converts spaces, underscores, and path separators to hyphens,
    strips any characters outside [a-z0-9-], collapses repeated hyphens, and trims
    hyphens from ends. Guarantees the result is never empty, '.', '..', or contains
    path traversal sequences. Returns 'project' if the resulting slug is empty.

    Examples:
        'Payment Service' -> 'payment-service'
        'API_v2!' -> 'api-v2'
        '..' -> 'project'
        '' -> 'project'
    """
    normalized_text = name.lower()
    # Convert spaces, underscores, and path separators to hyphens
    normalized_text = re.sub(r"[\s_/\\]+", "-", normalized_text)
    # Strip characters outside [a-z0-9-]
    normalized_text = re.sub(r"[^a-z0-9-]+", "", normalized_text)
    # Collapse repeated hyphens
    normalized_text = re.sub(r"-+", "-", normalized_text)
    # Trim leading and trailing hyphens
    result = normalized_text.strip("-")

    if not result or result in (".", ".."):
        return "project"
    return result


def _default_prompt(question: str, default: str | None = None) -> str:
    """Prompt the user for input via stdin with an optional default value."""
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


def resolve_project_name(
    repo_root: Path,
    override: str | None = None,
    interactive: bool = True,
    prompt_function: Callable[[str, str | None], str] | None = None,
) -> str:
    """Resolve the project name for the current repository.

    Priority order:
    1. CLI override (slugified, NOT saved to git config).
    2. Stored configuration in repository: `git config --local ghlog.project` (slugified).
    3. Interactive prompt with default slugify(repo_root.name). The user's answer
       is slugified and saved with `git config --local ghlog.project <slug>`.

    Args:
        repo_root: Path to the root directory of the working git repository.
        override: Optional CLI override passed via --project.
        interactive: Whether to prompt the user if no stored project name exists.
        prompt_function: Optional prompt callable (defaults to input prompt helper).

    Returns:
        The validated and slugified project name.
    """
    if override is not None:
        return slugify(override)

    try:
        stored_project = run_git(
            ["config", "--local", "ghlog.project"], cwd=repo_root, check=False
        ).strip()
        if stored_project:
            return slugify(stored_project)
    except GitError:
        pass

    default_slug = slugify(repo_root.name)

    if not interactive:
        return default_slug

    actual_prompt = prompt_function if prompt_function is not None else _default_prompt
    question = "Project name in the log repo"
    user_response = actual_prompt(question, default=default_slug)

    chosen_slug = slugify(user_response)
    run_git(["config", "--local", "--", "ghlog.project", chosen_slug], cwd=repo_root)

    return chosen_slug
