#!/usr/bin/env python3
"""
Comprehensive unit tests for opensepia.integrations.providers.github.

All HTTP/urllib calls are mocked — no real API requests are made.
"""

import json
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from opensepia.integrations.providers.github import (
    GitHubConfig,
    GitHubProvider,
    _github_headers,
    _api_call,
    ensure_labels,
    GITHUB_LABEL_COLORS,
)
from opensepia.integrations.base import BOARD_LABELS, PRIORITY_LABELS, ROLE_LABELS


# =============================================================================
# Helpers
# =============================================================================

def _make_response(data, code=200):
    """Create a fake urllib response object."""
    body = json.dumps(data).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = code
    return resp


def _make_http_error(code, body="", headers=None):
    """Create a urllib.error.HTTPError."""
    fp = BytesIO(body.encode("utf-8") if isinstance(body, str) else body)
    err = urllib.error.HTTPError(
        url="https://api.github.com/test",
        code=code,
        msg=f"HTTP {code}",
        hdrs=headers or {},
        fp=fp,
    )
    return err


def _get_call_data(mock_call):
    """Extract the 'data' dict from an _api_call mock invocation."""
    args, kwargs = mock_call
    if "data" in kwargs:
        return kwargs["data"]
    if len(args) > 3:
        return args[3]
    return None


def _get_call_params(mock_call):
    """Extract the 'params' dict from an _api_call mock invocation."""
    args, kwargs = mock_call
    if "params" in kwargs:
        return kwargs["params"]
    if len(args) > 4:
        return args[4]
    return None


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def config():
    """GitHubConfig with test values (no env dependency)."""
    cfg = GitHubConfig.__new__(GitHubConfig)
    cfg.token = "ghp_testtoken123"
    cfg.owner = "test-owner"
    cfg.repo = "test-repo"
    cfg.api_url = "https://api.github.com"
    return cfg


@pytest.fixture
def empty_config():
    """GitHubConfig with no credentials."""
    cfg = GitHubConfig.__new__(GitHubConfig)
    cfg.token = ""
    cfg.owner = ""
    cfg.repo = ""
    cfg.api_url = "https://api.github.com"
    return cfg


@pytest.fixture
def provider(config):
    """GitHubProvider with test config."""
    return GitHubProvider(config)


@pytest.fixture
def disabled_provider(empty_config):
    """GitHubProvider that is not enabled."""
    return GitHubProvider(empty_config)


# =============================================================================
# GitHubConfig
# =============================================================================

class TestGitHubConfig:

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "tok",
        "GITHUB_OWNER": "org",
        "GITHUB_REPO": "repo",
        "GITHUB_API_URL": "https://gh.example.com/",
    })
    def test_config_from_env(self):
        cfg = GitHubConfig()
        assert cfg.token == "tok"
        assert cfg.owner == "org"
        assert cfg.repo == "repo"
        # trailing slash stripped
        assert cfg.api_url == "https://gh.example.com"

    @patch.dict("os.environ", {}, clear=True)
    def test_config_defaults(self):
        cfg = GitHubConfig()
        assert cfg.token == ""
        assert cfg.owner == ""
        assert cfg.repo == ""
        assert cfg.api_url == "https://api.github.com"

    def test_api_base(self, config):
        assert config.api_base == "https://api.github.com/repos/test-owner/test-repo"

    def test_is_configured_true(self, config):
        assert config.is_configured is True

    def test_is_configured_false(self, empty_config):
        assert empty_config.is_configured is False

    def test_is_configured_partial(self):
        cfg = GitHubConfig.__new__(GitHubConfig)
        cfg.token = "tok"
        cfg.owner = "org"
        cfg.repo = ""
        cfg.api_url = "https://api.github.com"
        assert cfg.is_configured is False


# =============================================================================
# Headers helper
# =============================================================================

class TestGitHubHeaders:

    def test_headers_structure(self, config):
        h = _github_headers(config)
        assert h["Authorization"] == "Bearer ghp_testtoken123"
        assert h["Accept"] == "application/vnd.github+json"
        assert h["Content-Type"] == "application/json"
        assert "X-GitHub-Api-Version" in h


# =============================================================================
# Provider init & properties
# =============================================================================

class TestProviderProperties:

    def test_name(self, provider):
        assert provider.name == "github"

    def test_enabled_true(self, provider):
        assert provider.enabled is True

    def test_enabled_false(self, disabled_provider):
        assert disabled_provider.enabled is False

    def test_default_config_from_env(self):
        with patch.dict("os.environ", {
            "GITHUB_TOKEN": "t", "GITHUB_OWNER": "o", "GITHUB_REPO": "r",
        }):
            p = GitHubProvider()
            assert p.config.token == "t"

    def test_empty_cache_on_init(self, provider):
        assert provider._issue_cache == {}
        assert provider._cache_timestamps == {}


# =============================================================================
# init()
# =============================================================================

class TestProviderInit:

    @patch("opensepia.integrations.providers.github.ensure_labels")
    def test_init_calls_ensure_labels(self, mock_ensure, provider):
        provider.init()
        mock_ensure.assert_called_once_with(provider.config)

    @patch("opensepia.integrations.providers.github.ensure_labels")
    def test_init_skips_when_disabled(self, mock_ensure, disabled_provider):
        disabled_provider.init()
        mock_ensure.assert_not_called()


# =============================================================================
# Cache management
# =============================================================================

class TestCacheManagement:

    def test_clear_cache(self, provider):
        provider._issue_cache = {"STORY-001": 42}
        provider._cache_timestamps = {"STORY-001": time.time()}
        provider.clear_cache()
        assert provider._issue_cache == {}
        assert provider._cache_timestamps == {}


# =============================================================================
# _api_call
# =============================================================================

class TestApiCall:

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_api_call_get(self, mock_urlopen, config):
        mock_urlopen.return_value = _make_response({"id": 1})
        result = _api_call(config, "GET", "/issues")
        assert result == {"id": 1}

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_api_call_post_with_data(self, mock_urlopen, config):
        mock_urlopen.return_value = _make_response({"id": 2, "number": 2})
        result = _api_call(config, "POST", "/issues", data={"title": "test"})
        assert result["id"] == 2

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_api_call_with_params(self, mock_urlopen, config):
        mock_urlopen.return_value = _make_response([])
        _api_call(config, "GET", "/issues", params={"state": "open"})
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "state=open" in req.full_url

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_api_call_http_error(self, mock_urlopen, config):
        mock_urlopen.side_effect = _make_http_error(404, "not found")
        result = _api_call(config, "GET", "/issues/999", _max_retries=0)
        assert "error" in result

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_api_call_network_error(self, mock_urlopen, config):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        result = _api_call(config, "GET", "/issues")
        assert "error" in result


# =============================================================================
# Retry logic (via HTTPMixin._http_request_with_retry)
# =============================================================================

class TestRetryLogic:

    @patch("opensepia.integrations.providers.http_mixin.time.sleep")
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_retry_on_429(self, mock_urlopen, mock_sleep, config):
        """Should retry on 429 and eventually succeed."""
        err = _make_http_error(429, "rate limited", headers={})
        mock_urlopen.side_effect = [err, _make_response({"ok": True})]
        result = _api_call(config, "GET", "/issues", _max_retries=2)
        assert result == {"ok": True}
        assert mock_sleep.called

    @patch("opensepia.integrations.providers.http_mixin.time.sleep")
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_retry_on_403(self, mock_urlopen, mock_sleep, config):
        """GitHub rate limits also return 403; should retry."""
        err = _make_http_error(403, "rate limited", headers={})
        mock_urlopen.side_effect = [err, _make_response({"ok": True})]
        result = _api_call(config, "GET", "/issues", _max_retries=2)
        assert result == {"ok": True}

    @patch("opensepia.integrations.providers.http_mixin.time.sleep")
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_max_retries_exhausted(self, mock_urlopen, mock_sleep, config):
        """After exhausting retries, return error."""
        err = _make_http_error(429, "rate limited", headers={})
        mock_urlopen.side_effect = err  # always 429
        result = _api_call(config, "GET", "/issues", _max_retries=1)
        assert "error" in result

    @patch("opensepia.integrations.providers.http_mixin.time.sleep")
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_retry_respects_retry_after_header(self, mock_urlopen, mock_sleep, config):
        """Retry-After header should influence wait time."""
        headers = MagicMock()
        headers.get.return_value = "10"
        err = _make_http_error(429, "rate limited", headers=headers)
        mock_urlopen.side_effect = [err, _make_response({"ok": True})]
        _api_call(config, "GET", "/issues", _max_retries=2)
        # Should sleep for at least 10 seconds (from Retry-After)
        mock_sleep.assert_called()
        sleep_val = mock_sleep.call_args[0][0]
        assert sleep_val >= 10


# =============================================================================
# Issues
# =============================================================================

class TestCreateIssue:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_issue_basic(self, mock_api, provider):
        mock_api.return_value = {"id": 1, "number": 42, "title": "Test"}
        result = provider.create_issue("Test", "Description")
        assert result["iid"] == 42
        mock_api.assert_called_once()
        call_data = _get_call_data(mock_api.call_args)
        assert call_data["title"] == "Test"
        assert call_data["body"] == "Description"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_issue_with_labels(self, mock_api, provider):
        mock_api.return_value = {"id": 1, "number": 43, "title": "Test"}
        result = provider.create_issue("T", "D", labels=["status::todo", "priority::high"])
        call_data = _get_call_data(mock_api.call_args)
        assert call_data["labels"] == ["status::todo", "priority::high"]

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_issue_error(self, mock_api, provider):
        mock_api.return_value = {"error": 422, "message": "Validation failed"}
        result = provider.create_issue("T", "D")
        assert "error" in result
        assert "iid" not in result


class TestCloseReopen:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_close_issue(self, mock_api, provider):
        mock_api.return_value = {"number": 10, "state": "closed"}
        result = provider.close_issue(10)
        mock_api.assert_called_once_with(provider.config, "PATCH", "/issues/10",
                                         data={"state": "closed"})

    @patch("opensepia.integrations.providers.github._api_call")
    def test_reopen_issue(self, mock_api, provider):
        mock_api.return_value = {"number": 10, "state": "open"}
        provider.reopen_issue(10)
        mock_api.assert_called_once_with(provider.config, "PATCH", "/issues/10",
                                         data={"state": "open"})


class TestUpdateIssueLabels:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_update_labels(self, mock_api, provider):
        mock_api.return_value = {"number": 5}
        provider.update_issue_labels(5, ["status::done"])
        mock_api.assert_called_once_with(provider.config, "PATCH", "/issues/5",
                                         data={"labels": ["status::done"]})


class TestUpdateIssueStatus:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_status_transition(self, mock_api, provider):
        # First call: GET issue to read current labels
        mock_api.side_effect = [
            {
                "number": 7,
                "labels": [{"name": "status::todo"}, {"name": "priority::high"}],
            },
            # Second call: PATCH with updated labels
            {"number": 7, "labels": [{"name": "status::in-progress"}, {"name": "priority::high"}]},
        ]
        result = provider.update_issue_status(7, "todo", "in_progress")
        assert mock_api.call_count == 2
        patch_call = mock_api.call_args_list[1]
        new_labels = _get_call_data(patch_call)["labels"]
        assert "status::in-progress" in new_labels
        assert "status::todo" not in new_labels
        assert "priority::high" in new_labels

    @patch("opensepia.integrations.providers.github._api_call")
    def test_status_transition_error_on_get(self, mock_api, provider):
        mock_api.return_value = {"error": 404, "message": "not found"}
        result = provider.update_issue_status(999, "todo", "in_progress")
        assert "error" in result
        assert mock_api.call_count == 1


class TestCommentOnIssue:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_comment_formats_agent_prefix(self, mock_api, provider):
        mock_api.return_value = {"id": 100}
        provider.comment_on_issue(5, "dev1", "Looks good!")
        call_data = _get_call_data(mock_api.call_args)
        body = call_data["body"]
        assert "Developer 1" in body
        assert "dev1" in body
        assert "Looks good!" in body


class TestListIssues:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_list_issues_filters_prs(self, mock_api, provider):
        mock_api.return_value = [
            {"number": 1, "title": "Issue"},
            {"number": 2, "title": "PR", "pull_request": {"url": "..."}},
        ]
        result = provider.list_issues()
        assert len(result) == 1
        assert result[0]["iid"] == 1

    @patch("opensepia.integrations.providers.github._api_call")
    def test_list_issues_state_mapping(self, mock_api, provider):
        mock_api.return_value = []
        provider.list_issues(state="opened")
        params = _get_call_params(mock_api.call_args)
        assert params["state"] == "open"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_list_issues_with_labels(self, mock_api, provider):
        mock_api.return_value = []
        provider.list_issues(labels="status::todo")
        params = _get_call_params(mock_api.call_args)
        assert params["labels"] == "status::todo"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_list_issues_non_list_response(self, mock_api, provider):
        mock_api.return_value = {"error": "bad"}
        assert provider.list_issues() == []


class TestSearchIssues:

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_search_issues(self, mock_urlopen, provider):
        mock_urlopen.return_value = _make_response({
            "total_count": 1,
            "items": [{"number": 10, "title": "[STORY-001] Feature"}],
        })
        result = provider.search_issues("[STORY-001]")
        assert len(result) == 1
        assert result[0]["iid"] == 10

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_search_issues_error(self, mock_urlopen, provider):
        mock_urlopen.side_effect = _make_http_error(500, "server error")
        result = provider.search_issues("broken")
        assert result == []

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_search_issues_non_dict_response(self, mock_urlopen, provider):
        mock_urlopen.return_value = _make_response([])
        result = provider.search_issues("query")
        assert result == []


class TestGetIssueComments:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_get_comments(self, mock_api, provider):
        mock_api.return_value = [
            {
                "id": 1,
                "body": "nice work",
                "user": {"login": "alice"},
                "created_at": "2024-01-01T00:00:00Z",
            },
        ]
        result = provider.get_issue_comments(5)
        assert len(result) == 1
        assert result[0]["body"] == "nice work"
        assert result[0]["author"]["name"] == "alice"
        assert result[0]["system"] is False

    @patch("opensepia.integrations.providers.github._api_call")
    def test_get_comments_non_list(self, mock_api, provider):
        mock_api.return_value = {"error": 404}
        assert provider.get_issue_comments(999) == []

    @patch("opensepia.integrations.providers.github._api_call")
    def test_get_comments_limit(self, mock_api, provider):
        mock_api.return_value = []
        provider.get_issue_comments(5, limit=3)
        params = _get_call_params(mock_api.call_args)
        assert params["per_page"] == 3


# =============================================================================
# find_issue_by_id (cache TTL)
# =============================================================================

class TestFindIssueById:

    def test_memory_cache_hit(self, provider):
        provider._issue_cache["STORY-001"] = 42
        provider._cache_timestamps["STORY-001"] = time.time()
        assert provider.find_issue_by_id("STORY-001") == 42

    def test_memory_cache_expired(self, provider):
        provider._issue_cache["STORY-001"] = 42
        provider._cache_timestamps["STORY-001"] = time.time() - 600  # expired

        # File cache miss, API miss
        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch.object(provider, "search_issues", return_value=[]):
                result = provider.find_issue_by_id("STORY-001")
        assert result is None
        assert "STORY-001" not in provider._issue_cache

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_file_cache_miss_api_search_hit(self, mock_open_fn, provider):
        with patch.object(provider, "search_issues", return_value=[
            {"number": 55, "title": "[STORY-002] Feature X"},
        ]):
            result = provider.find_issue_by_id("STORY-002")
        assert result == 55
        assert provider._issue_cache["STORY-002"] == 55

    def test_file_cache_hit(self, provider):
        cache_data = json.dumps({"STORY-003": 99})
        m = mock_open(read_data=cache_data)
        with patch("builtins.open", m):
            result = provider.find_issue_by_id("STORY-003")
        assert result == 99
        assert provider._issue_cache["STORY-003"] == 99

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_api_search_no_match(self, mock_open_fn, provider):
        with patch.object(provider, "search_issues", return_value=[
            {"number": 10, "title": "[STORY-999] Other"},
        ]):
            result = provider.find_issue_by_id("STORY-001")
        assert result is None

    def test_file_cache_json_error(self, provider):
        m = mock_open(read_data="not-json")
        with patch("builtins.open", m):
            with patch.object(provider, "search_issues", return_value=[]):
                result = provider.find_issue_by_id("STORY-X")
        assert result is None


# =============================================================================
# Board state
# =============================================================================

class TestBoardState:

    @patch.object(GitHubProvider, "list_issues")
    def test_get_board_state(self, mock_list, provider):
        mock_list.return_value = [
            {"number": 1, "title": "Task", "labels": [{"name": "status::todo"}], "updated_at": "2024-01-01"},
        ]
        state = provider.get_board_state()
        assert "todo" in state
        assert len(state["todo"]) == 1
        assert state["todo"][0]["iid"] == 1
        # Called once per status in BOARD_LABELS
        assert mock_list.call_count == len(BOARD_LABELS)

    def test_get_board_summary_disabled(self, disabled_provider):
        assert "not active" in disabled_provider.get_board_summary_md()

    @patch.object(GitHubProvider, "get_board_state")
    def test_get_board_summary_md(self, mock_state, provider):
        mock_state.return_value = {
            "todo": [{"iid": 1, "title": "Do X", "labels": ["priority::high"], "updated_at": ""}],
            "in_progress": [],
            "review": [],
            "testing": [],
            "done": [],
            "blocked": [],
        }
        md = provider.get_board_summary_md()
        assert "TODO" in md
        assert "#1" in md
        assert "Do X" in md
        assert "high" in md
        assert "_(empty)_" in md


# =============================================================================
# Pull Requests (MRs)
# =============================================================================

class TestPullRequests:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_mr(self, mock_api, provider):
        mock_api.return_value = {"number": 10, "title": "My PR"}
        result = provider.create_mr("feature", "main", title="My PR")
        assert result["iid"] == 10
        call_data = _get_call_data(mock_api.call_args)
        assert call_data["head"] == "feature"
        assert call_data["base"] == "main"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_mr_default_title(self, mock_api, provider):
        mock_api.return_value = {"number": 11}
        provider.create_mr("feat", "main")
        call_data = _get_call_data(mock_api.call_args)
        assert "feat" in call_data["title"]

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_mr_error(self, mock_api, provider):
        mock_api.return_value = {"error": 422}
        result = provider.create_mr("feat", "main")
        assert "error" in result
        assert "iid" not in result

    @patch("opensepia.integrations.providers.github._api_call")
    def test_list_mrs(self, mock_api, provider):
        mock_api.return_value = [
            {
                "number": 5,
                "title": "PR",
                "head": {"ref": "feat-1"},
                "base": {"ref": "main"},
                "user": {"login": "alice"},
            },
        ]
        result = provider.list_mrs()
        assert len(result) == 1
        assert result[0]["iid"] == 5
        assert result[0]["source_branch"] == "feat-1"
        assert result[0]["target_branch"] == "main"
        assert result[0]["author"]["name"] == "alice"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_list_mrs_non_list(self, mock_api, provider):
        mock_api.return_value = {"error": "bad"}
        assert provider.list_mrs() == []

    @patch("opensepia.integrations.providers.github._api_call")
    def test_get_mr(self, mock_api, provider):
        mock_api.return_value = {"number": 3, "title": "Fix"}
        result = provider.get_mr(3)
        assert result["iid"] == 3

    @patch("opensepia.integrations.providers.github._api_call")
    def test_get_mr_error(self, mock_api, provider):
        mock_api.return_value = {"error": 404}
        result = provider.get_mr(999)
        assert "iid" not in result

    @patch("opensepia.integrations.providers.github._api_call")
    def test_comment_on_mr_with_agent(self, mock_api, provider):
        mock_api.return_value = {"id": 50}
        provider.comment_on_mr(5, "Review OK", agent_id="tester")
        call_data = _get_call_data(mock_api.call_args)
        assert "TESTER" in call_data["body"]
        assert "Review OK" in call_data["body"]

    @patch("opensepia.integrations.providers.github._api_call")
    def test_comment_on_mr_no_agent(self, mock_api, provider):
        mock_api.return_value = {"id": 51}
        provider.comment_on_mr(5, "plain comment")
        call_data = _get_call_data(mock_api.call_args)
        assert call_data["body"] == "plain comment"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_approve_mr(self, mock_api, provider):
        mock_api.return_value = {"id": 1}
        provider.approve_mr(5)
        mock_api.assert_called_once_with(provider.config, "POST",
                                         "/pulls/5/reviews",
                                         data={"event": "APPROVE"})

    @patch("opensepia.integrations.providers.github._api_call")
    def test_merge_mr_default(self, mock_api, provider):
        mock_api.return_value = {"merged": True}
        provider.merge_mr(5)
        call_data = _get_call_data(mock_api.call_args)
        assert call_data["merge_method"] == "merge"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_merge_mr_squash(self, mock_api, provider):
        mock_api.return_value = {"merged": True}
        provider.merge_mr(5, squash=True)
        call_data = _get_call_data(mock_api.call_args)
        assert call_data["merge_method"] == "squash"

    @patch("opensepia.integrations.providers.github._api_call")
    def test_close_mr(self, mock_api, provider):
        mock_api.return_value = {"state": "closed"}
        provider.close_mr(5)
        mock_api.assert_called_once_with(provider.config, "PATCH", "/pulls/5",
                                         data={"state": "closed"})

    @patch("opensepia.integrations.providers.github._api_call")
    def test_get_mr_changes(self, mock_api, provider):
        mock_api.return_value = [{"filename": "a.py"}]
        result = provider.get_mr_changes(5)
        assert result == [{"filename": "a.py"}]


class TestMrApprovals:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_approved(self, mock_api, provider):
        mock_api.return_value = [{"state": "APPROVED", "user": {"login": "a"}}]
        result = provider.get_mr_approvals(5)
        assert result["approved"] is True

    @patch("opensepia.integrations.providers.github._api_call")
    def test_not_approved(self, mock_api, provider):
        mock_api.return_value = [{"state": "CHANGES_REQUESTED"}]
        result = provider.get_mr_approvals(5)
        assert result["approved"] is False

    @patch("opensepia.integrations.providers.github._api_call")
    def test_approvals_error(self, mock_api, provider):
        mock_api.return_value = {"error": 404}
        result = provider.get_mr_approvals(5)
        assert result["approved"] is False
        assert "error" in result


class TestOpenMrsMd:

    @patch.object(GitHubProvider, "list_mrs")
    def test_no_mrs(self, mock_list, provider):
        mock_list.return_value = []
        md = provider.get_open_mrs_md()
        assert "_(none)_" in md

    @patch.object(GitHubProvider, "list_mrs")
    def test_with_mrs(self, mock_list, provider):
        mock_list.return_value = [
            {
                "number": 3,
                "title": "Add feature",
                "author": {"name": "bob"},
                "source_branch": "feat",
                "target_branch": "main",
            },
        ]
        md = provider.get_open_mrs_md()
        assert "#3" in md
        assert "Add feature" in md
        assert "feat" in md
        assert "bob" in md


# =============================================================================
# ensure_labels
# =============================================================================

class TestEnsureLabels:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_creates_missing_labels(self, mock_api, config):
        # GET returns empty list (no existing labels)
        mock_api.side_effect = lambda cfg, method, endpoint, **kw: (
            [] if method == "GET" else {"name": "created"}
        )
        ensure_labels(config)
        # Should have been called: 1 GET + N POSTs for each missing label
        post_calls = [c for c in mock_api.call_args_list if c[0][1] == "POST"]
        assert len(post_calls) == len(GITHUB_LABEL_COLORS)

    @patch("opensepia.integrations.providers.github._api_call")
    def test_skips_existing_labels(self, mock_api, config):
        existing = [{"name": name} for name in GITHUB_LABEL_COLORS.keys()]
        mock_api.return_value = existing
        ensure_labels(config)
        post_calls = [c for c in mock_api.call_args_list if c[0][1] == "POST"]
        assert len(post_calls) == 0

    @patch("opensepia.integrations.providers.github._api_call")
    def test_pagination(self, mock_api, config):
        """Handles paginated label listing."""
        page1 = [{"name": f"label-{i}"} for i in range(100)]
        page2 = [{"name": "status::todo"}]
        call_count = {"n": 0}

        def side_effect(cfg, method, endpoint, **kw):
            if method == "GET" and endpoint == "/labels":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return page1
                return page2
            return {"name": "ok"}

        mock_api.side_effect = side_effect
        ensure_labels(config)
        # Should have made 2 GET calls for pagination
        get_calls = [c for c in mock_api.call_args_list
                     if c[0][1] == "GET" and c[0][2] == "/labels"]
        assert len(get_calls) == 2


# =============================================================================
# create_story (high-level alias using base class + caching)
# =============================================================================

class TestCreateStory:

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_story_caches_number(self, mock_api, provider):
        mock_api.return_value = {"number": 77, "title": "[STORY-010] Feature"}
        provider.create_story("STORY-010", "Feature", "Description", priority="high")
        assert provider._issue_cache["STORY-010"] == 77
        assert "STORY-010" in provider._cache_timestamps

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_story_labels(self, mock_api, provider):
        mock_api.return_value = {"number": 78, "title": "test"}
        provider.create_story("STORY-011", "X", "Y", priority="critical", assigned_to="dev")
        call_data = _get_call_data(mock_api.call_args)
        assert "status::todo" in call_data["labels"]
        assert "priority::critical" in call_data["labels"]
        assert "role::developer" in call_data["labels"]

    @patch("opensepia.integrations.providers.github._api_call")
    def test_create_story_no_number_no_cache(self, mock_api, provider):
        mock_api.return_value = {"error": 422}
        provider.create_story("STORY-012", "X", "Y")
        assert "STORY-012" not in provider._issue_cache


# =============================================================================
# Cache TTL behavior
# =============================================================================

class TestCacheTTL:

    def test_cache_ttl_constant(self):
        assert GitHubProvider.CACHE_TTL_SECONDS == 300

    def test_fresh_cache_used(self, provider):
        provider._issue_cache["S-1"] = 10
        provider._cache_timestamps["S-1"] = time.time()  # just now
        assert provider.find_issue_by_id("S-1") == 10

    def test_stale_cache_evicted(self, provider):
        provider._issue_cache["S-2"] = 20
        provider._cache_timestamps["S-2"] = time.time() - 301  # 1 second past TTL

        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch.object(provider, "search_issues", return_value=[]):
                result = provider.find_issue_by_id("S-2")
        assert result is None
        assert "S-2" not in provider._issue_cache
        assert "S-2" not in provider._cache_timestamps


# =============================================================================
# Error handling edge cases
# =============================================================================

class TestErrorHandling:

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_json_decode_error(self, mock_urlopen, config):
        """Non-JSON response should return error dict."""
        resp = MagicMock()
        resp.read.return_value = b"not json at all"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp
        result = _api_call(config, "GET", "/issues")
        assert "error" in result

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_empty_response_body(self, mock_urlopen, config):
        """Empty response body should return ok."""
        resp = MagicMock()
        resp.read.return_value = b""
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp
        result = _api_call(config, "GET", "/issues/5")
        assert result == {"status": "ok"}

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_os_error(self, mock_urlopen, config):
        mock_urlopen.side_effect = OSError("connection reset")
        result = _api_call(config, "GET", "/issues")
        assert "error" in result
