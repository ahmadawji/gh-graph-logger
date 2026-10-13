"""Unit tests for project slugification and name resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_graph_logger.gitutil import run_git
from gh_graph_logger.project import resolve_project_name, slugify


@pytest.mark.parametrize(
    ("input_name", "expected_slug"),
    [
        ("Payment Service", "payment-service"),
        ("API_v2!", "api-v2"),
        ("", "project"),
        ("..", "project"),
        (".", "project"),
        ("---", "project"),
        ("   ", "project"),
        ("!@#$%^&*()", "project"),
        ("foo/bar\\baz", "foo-bar-baz"),
        ("path/to/my_service", "path-to-my-service"),
        ("  --  multiple   spaces  --  ", "multiple-spaces"),
        ("unicode-🚀-test", "unicode-test"),
        ("already-valid-slug-123", "already-valid-slug-123"),
    ],
)
def test_slugify(input_name: str, expected_slug: str) -> None:
    """Verify slugify normalization across standard cases and edge cases."""
    assert slugify(input_name) == expected_slug


def test_resolve_project_name_first_time_prompts_and_persists(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First-time resolution prompts for project name and persists in repo config."""
    inputs = ["My Custom Service"]
    monkeypatch.setattr("builtins.input", lambda _: inputs.pop(0))

    resolved = resolve_project_name(git_repo)
    assert resolved == "my-custom-service"

    # Verify persisted in local git config
    stored = run_git(["config", "--local", "ghlog.project"], cwd=git_repo)
    assert stored == "my-custom-service"

    # Second call should not prompt and return stored value
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Should not prompt again"))
    second_resolved = resolve_project_name(git_repo)
    assert second_resolved == "my-custom-service"


def test_resolve_project_name_override_not_saved(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--project override takes precedence, is slugified, but is not saved to git config."""
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Should not prompt on override"))

    resolved = resolve_project_name(git_repo, override="Temporary Override!")
    assert resolved == "temporary-override"

    # Verify not stored in local git config
    config_result = run_git(
        ["config", "--local", "ghlog.project"], cwd=git_repo, check=False
    )
    assert config_result == ""


def test_resolve_project_name_non_interactive_uses_default(git_repo: Path) -> None:
    """When interactive=False and no config stored, default slug is used and not saved."""
    resolved = resolve_project_name(git_repo, interactive=False)
    assert resolved == slugify(git_repo.name)

    config_result = run_git(
        ["config", "--local", "ghlog.project"], cwd=git_repo, check=False
    )
    assert config_result == ""
