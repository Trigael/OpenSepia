"""Tests for integrations/providers/__init__.py — provider detection."""

from opensepia.integrations.providers import detect_provider


def test_detect_provider_returns_markdown_fallback_when_no_env_vars(clean_env):
    result = detect_provider()
    # With no external provider configured, falls back to markdown (or None)
    assert result is None or result.name == "markdown"


def test_detect_provider_returns_gitlab_when_gitlab_env_set(clean_env):
    mp = clean_env
    mp.setenv("GITLAB_URL", "https://gitlab.example.com")
    mp.setenv("GITLAB_TOKEN", "fake-token-123")
    mp.setenv("GITLAB_PROJECT_ID", "42")

    result = detect_provider()
    assert result is not None
    assert result.name == "gitlab"


def test_detect_provider_returns_github_when_github_env_set(clean_env):
    mp = clean_env
    mp.setenv("GITHUB_TOKEN", "ghp_fake_token")
    mp.setenv("GITHUB_OWNER", "test-owner")
    mp.setenv("GITHUB_REPO", "test-repo")

    result = detect_provider()
    assert result is not None
    assert result.name == "github"


def test_detect_provider_gitlab_takes_priority(clean_env):
    mp = clean_env
    # Set both GitLab and GitHub env vars
    mp.setenv("GITLAB_URL", "https://gitlab.example.com")
    mp.setenv("GITLAB_TOKEN", "fake-token-123")
    mp.setenv("GITLAB_PROJECT_ID", "42")
    mp.setenv("GITHUB_TOKEN", "ghp_fake_token")
    mp.setenv("GITHUB_OWNER", "test-owner")
    mp.setenv("GITHUB_REPO", "test-repo")

    result = detect_provider()
    assert result is not None
    assert result.name == "gitlab"


def test_detect_provider_returns_fallback_with_partial_gitlab(clean_env):
    mp = clean_env
    # Only GITLAB_URL set, missing TOKEN — should NOT get GitLab
    mp.setenv("GITLAB_URL", "https://gitlab.example.com")

    result = detect_provider()
    # Falls back to markdown provider (or None if no board dir)
    assert result is None or result.name == "markdown"
    if result:
        assert result.name != "gitlab"


def test_detect_provider_returns_fallback_with_partial_github(clean_env):
    mp = clean_env
    # Only GITHUB_TOKEN set, missing REPO — should NOT get GitHub
    mp.setenv("GITHUB_TOKEN", "ghp_fake_token")

    result = detect_provider()
    # Falls back to markdown provider (or None if no board dir)
    assert result is None or result.name == "markdown"
    if result:
        assert result.name != "github"
