#!/usr/bin/env python3
"""
Comprehensive unit tests for opensepia.integrations.providers.gitlab
"""

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

from opensepia.integrations.providers.gitlab import (
    GitLabConfig,
    GitLabProvider,
    _gitlab_headers,
    _api_call,
    ensure_labels,
    setup_board,
    GITLAB_LABEL_COLORS,
)
from opensepia.integrations.base import BOARD_LABELS


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def config():
    """GitLabConfig with test values (bypass env vars)."""
    cfg = GitLabConfig.__new__(GitLabConfig)
    cfg.url = "https://gitlab.example.com"
    cfg.token = "test-token-123"
    cfg.project_id = "my-group/my-project"
    return cfg


@pytest.fixture
def provider(config):
    return GitLabProvider(config)


@pytest.fixture
def unconfigured_config():
    cfg = GitLabConfig.__new__(GitLabConfig)
    cfg.url = ""
    cfg.token = ""
    cfg.project_id = ""
    return cfg


# Helper to mock _api_call
def patch_api(return_value):
    return patch(
        "opensepia.integrations.providers.gitlab._api_call",
        return_value=return_value,
    )


# =============================================================================
# GitLabConfig
# =============================================================================

class TestGitLabConfig:
    def test_api_base(self, config):
        assert config.api_base == "https://gitlab.example.com/api/v4/projects/my-group%2Fmy-project"

    def test_is_configured(self, config):
        assert config.is_configured is True

    def test_not_configured_missing_url(self, config):
        config.url = ""
        assert config.is_configured is False

    def test_not_configured_missing_token(self, config):
        config.token = ""
        assert config.is_configured is False

    def test_not_configured_missing_project_id(self, config):
        config.project_id = ""
        assert config.is_configured is False

    def test_init_from_env(self):
        env = {
            "GITLAB_URL": "https://gl.test.com/",
            "GITLAB_TOKEN": "tok",
            "GITLAB_PROJECT_ID": "123",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = GitLabConfig()
        assert cfg.url == "https://gl.test.com"  # trailing slash stripped
        assert cfg.token == "tok"
        assert cfg.project_id == "123"

    def test_init_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            cfg = GitLabConfig()
        assert cfg.url == ""
        assert cfg.token == ""
        assert cfg.project_id == ""


# =============================================================================
# Headers helper
# =============================================================================

class TestHeaders:
    def test_gitlab_headers(self, config):
        h = _gitlab_headers(config)
        assert h["PRIVATE-TOKEN"] == "test-token-123"
        assert h["Content-Type"] == "application/json"


# =============================================================================
# _api_call
# =============================================================================

class TestApiCall:
    @patch("opensepia.integrations.providers.gitlab.HTTPMixin._http_request_with_retry")
    def test_api_call_get(self, mock_http, config):
        mock_http.return_value = [{"id": 1}]
        result = _api_call(config, "GET", "/issues", params={"state": "opened"})
        assert result == [{"id": 1}]
        call_args = mock_http.call_args
        assert "/issues?" in call_args[0][0]
        assert call_args[1]["method"] == "GET"

    @patch("opensepia.integrations.providers.gitlab.HTTPMixin._http_request_with_retry")
    def test_api_call_post(self, mock_http, config):
        mock_http.return_value = {"iid": 5}
        result = _api_call(config, "POST", "/issues", data={"title": "Test"})
        assert result == {"iid": 5}
        assert mock_http.call_args[1]["data"] == {"title": "Test"}

    @patch("opensepia.integrations.providers.gitlab.HTTPMixin._http_request_with_retry")
    def test_api_call_error(self, mock_http, config):
        mock_http.return_value = {"error": 500, "message": "Internal Server Error"}
        result = _api_call(config, "GET", "/issues")
        assert "error" in result


# =============================================================================
# ensure_labels
# =============================================================================

class TestEnsureLabels:
    def test_creates_missing_labels(self, config):
        existing = [{"name": "status::todo"}]
        call_results = [existing]  # first call: GET /labels
        # subsequent POST calls return success
        def side_effect(cfg, method, endpoint, **kwargs):
            if method == "GET":
                return call_results[0]
            return {"name": kwargs.get("data", {}).get("name", ""), "id": 99}

        with patch("opensepia.integrations.providers.gitlab._api_call", side_effect=side_effect):
            ensure_labels(config)

    def test_skips_on_api_error(self, config):
        with patch_api({"error": "unauthorized"}):
            ensure_labels(config)  # should not raise

    def test_skips_existing_labels(self, config):
        all_labels = [{"name": name} for name in GITLAB_LABEL_COLORS]
        calls = []

        def side_effect(cfg, method, endpoint, **kwargs):
            calls.append((method, endpoint))
            if method == "GET":
                return all_labels
            return {"name": "x"}

        with patch("opensepia.integrations.providers.gitlab._api_call", side_effect=side_effect):
            ensure_labels(config)

        # Only one GET for existing labels; no POSTs because all exist
        assert all(c[0] == "GET" for c in calls)


# =============================================================================
# setup_board
# =============================================================================

class TestSetupBoard:
    def test_setup_board_existing(self, config):
        responses = {
            ("GET", "/labels"): [{"name": n} for n in GITLAB_LABEL_COLORS],
            ("GET", "/boards"): [{"id": 42}],
            ("GET", "/boards/42/lists"): [
                {"label": {"name": BOARD_LABELS[k]}}
                for k in BOARD_LABELS
            ],
        }

        def side_effect(cfg, method, endpoint, **kwargs):
            key = (method, endpoint)
            if key in responses:
                return responses[key]
            # label search fallback
            if method == "GET" and "/labels" in endpoint:
                return responses[("GET", "/labels")]
            return {"status": "ok"}

        with patch("opensepia.integrations.providers.gitlab._api_call", side_effect=side_effect):
            setup_board(config)

    def test_setup_board_creates_new(self, config):
        created = []

        def side_effect(cfg, method, endpoint, **kwargs):
            if method == "GET" and endpoint == "/labels":
                params = kwargs.get("params", {})
                if "search" in params:
                    return [{"id": 10, "name": params["search"]}]
                return [{"name": n} for n in GITLAB_LABEL_COLORS]
            if method == "GET" and endpoint == "/boards":
                return []  # no boards
            if method == "POST" and endpoint == "/boards":
                return {"id": 99}
            if method == "GET" and "/boards/" in endpoint and "/lists" in endpoint:
                return []  # no lists
            if method == "POST" and "/lists" in endpoint:
                created.append(endpoint)
                return {"id": 1}
            return {"status": "ok"}

        with patch("opensepia.integrations.providers.gitlab._api_call", side_effect=side_effect):
            setup_board(config)

        assert len(created) == 5  # 5 status columns

    def test_setup_board_no_board_id(self, config):
        def side_effect(cfg, method, endpoint, **kwargs):
            if method == "GET" and endpoint == "/labels":
                return [{"name": n} for n in GITLAB_LABEL_COLORS]
            if method == "GET" and endpoint == "/boards":
                return []
            if method == "POST" and endpoint == "/boards":
                return {"error": "forbidden"}  # no id
            return []

        with patch("opensepia.integrations.providers.gitlab._api_call", side_effect=side_effect):
            setup_board(config)  # should not raise


# =============================================================================
# GitLabProvider — initialization and properties
# =============================================================================

class TestProviderInit:
    def test_name(self, provider):
        assert provider.name == "gitlab"

    def test_enabled_configured(self, provider):
        assert provider.enabled is True

    def test_enabled_unconfigured(self, unconfigured_config):
        p = GitLabProvider(unconfigured_config)
        assert p.enabled is False

    def test_default_config(self):
        with patch.dict("os.environ", {}, clear=True):
            p = GitLabProvider()
        assert p.enabled is False

    def test_init_when_not_enabled(self, unconfigured_config):
        p = GitLabProvider(unconfigured_config)
        p.init()  # should just warn, not raise

    def test_init_calls_setup_board(self, provider):
        with patch("opensepia.integrations.providers.gitlab.setup_board") as mock_sb:
            provider.init()
            mock_sb.assert_called_once_with(provider.config)


# =============================================================================
# Cache management
# =============================================================================

class TestCacheManagement:
    def test_clear_cache(self, provider):
        provider._issue_cache["STORY-001"] = 42
        provider.clear_cache()
        assert provider._issue_cache == {}


# =============================================================================
# Issues
# =============================================================================

class TestIssues:
    def test_create_issue(self, provider):
        with patch_api({"iid": 10, "title": "Test"}) as mock:
            result = provider.create_issue("Test", "desc", labels=["status::todo"])
        assert result["iid"] == 10
        call_data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "status::todo" in call_data.get("labels", "")

    def test_create_issue_with_kwargs(self, provider):
        with patch_api({"iid": 11}) as mock:
            provider.create_issue("T", "D", milestone_id=3, weight=5)
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["milestone_id"] == 3
        assert data["weight"] == 5

    def test_create_issue_error(self, provider):
        with patch_api({"error": 422, "message": "bad"}):
            result = provider.create_issue("T", "D")
        assert "error" in result

    def test_close_issue(self, provider):
        with patch_api({"state": "closed"}) as mock:
            result = provider.close_issue(10)
        assert result["state"] == "closed"

    def test_reopen_issue(self, provider):
        with patch_api({"state": "opened"}) as mock:
            provider.reopen_issue(10)
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["state_event"] == "reopen"

    def test_update_issue_labels(self, provider):
        with patch_api({"labels": ["a", "b"]}):
            result = provider.update_issue_labels(10, ["a", "b"])
        assert result["labels"] == ["a", "b"]

    def test_update_issue_status(self, provider):
        with patch_api({"iid": 10}) as mock:
            provider.update_issue_status(10, "todo", "in_progress")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["remove_labels"] == "status::todo"
        assert data["add_labels"] == "status::in-progress"

    def test_update_issue_status_unknown_from(self, provider):
        with patch_api({"iid": 10}) as mock:
            provider.update_issue_status(10, "nonexistent", "done")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "remove_labels" not in data
        assert data["add_labels"] == "status::done"

    def test_comment_on_issue(self, provider):
        with patch_api({"id": 1}) as mock:
            provider.comment_on_issue(10, "dev1", "hello")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "dev1" in data["body"]
        assert "hello" in data["body"]

    def test_list_issues(self, provider):
        with patch_api([{"iid": 1}, {"iid": 2}]):
            result = provider.list_issues(labels="status::todo", state="opened")
        assert len(result) == 2

    def test_list_issues_error_returns_empty(self, provider):
        with patch_api({"error": 500}):
            result = provider.list_issues()
        assert result == []

    def test_search_issues(self, provider):
        with patch_api([{"iid": 3, "title": "[STORY-001] Test"}]):
            result = provider.search_issues("[STORY-001]")
        assert len(result) == 1

    def test_search_issues_error_returns_empty(self, provider):
        with patch_api({"error": 404}):
            result = provider.search_issues("xyz")
        assert result == []

    def test_get_issue_comments(self, provider):
        with patch_api([{"id": 1, "body": "note"}]):
            result = provider.get_issue_comments(10, limit=5)
        assert len(result) == 1

    def test_get_issue_comments_error(self, provider):
        with patch_api({"error": 500}):
            result = provider.get_issue_comments(10)
        assert result == []


# =============================================================================
# find_issue_by_id
# =============================================================================

class TestFindIssueById:
    def test_from_memory_cache(self, provider):
        provider._issue_cache["STORY-001"] = 42
        assert provider.find_issue_by_id("STORY-001") == 42

    def test_from_file_cache(self, provider, tmp_path):
        cache_file = tmp_path / ".gitlab_issue_map.json"
        cache_file.write_text(json.dumps({"STORY-002": 55}))

        with patch("opensepia.integrations.providers.gitlab.Path") as mock_path:
            # __file__ -> parent -> parent -> parent / "board" / file
            mock_path.return_value.parent.parent.parent.__truediv__.return_value.__truediv__.return_value = cache_file
            # Actually, we need to mock Path(__file__) chain
            # Simpler: mock open
            pass

        # Use a different approach: mock builtins.open via the json import path
        import builtins
        original_open = builtins.open
        cache_data = json.dumps({"STORY-002": 55})

        def mock_open(path, *args, **kwargs):
            if ".gitlab_issue_map.json" in str(path):
                from io import StringIO
                return StringIO(cache_data)
            return original_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            result = provider.find_issue_by_id("STORY-002")
        assert result == 55
        assert provider._issue_cache["STORY-002"] == 55

    def test_file_cache_not_found(self, provider):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch_api([{"iid": 77, "title": "[STORY-003] Foo"}]):
                result = provider.find_issue_by_id("STORY-003")
        assert result == 77
        assert provider._issue_cache["STORY-003"] == 77

    def test_not_found(self, provider):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch_api([]):
                result = provider.find_issue_by_id("STORY-999")
        assert result is None

    def test_file_cache_json_error(self, provider):
        from io import StringIO
        with patch("builtins.open", return_value=StringIO("not json{")):
            with patch_api([]):
                result = provider.find_issue_by_id("STORY-404")
        assert result is None


# =============================================================================
# Board
# =============================================================================

class TestBoard:
    def test_get_board_state(self, provider):
        def side_effect(cfg, method, endpoint, **kwargs):
            return [{"iid": 1, "title": "Test", "labels": ["status::todo"], "updated_at": "2025-01-01"}]

        with patch("opensepia.integrations.providers.gitlab._api_call", side_effect=side_effect):
            state = provider.get_board_state()

        assert "todo" in state
        assert len(state["todo"]) == 1
        assert state["todo"][0]["iid"] == 1

    def test_get_board_summary_md_disabled(self, unconfigured_config):
        p = GitLabProvider(unconfigured_config)
        result = p.get_board_summary_md()
        assert "not active" in result

    def test_get_board_summary_md_enabled(self, provider):
        def side_effect(cfg, method, endpoint, **kwargs):
            labels_param = kwargs.get("params", {}).get("labels", "")
            if "todo" in labels_param:
                return [{"iid": 1, "title": "A", "labels": ["status::todo", "priority::high"], "updated_at": ""}]
            return []

        with patch("opensepia.integrations.providers.gitlab._api_call", side_effect=side_effect):
            md = provider.get_board_summary_md()

        assert "Board" in md
        assert "TODO" in md
        assert "#1" in md


# =============================================================================
# Merge Requests
# =============================================================================

class TestMergeRequests:
    def test_create_mr(self, provider):
        with patch_api({"iid": 1, "title": "MR"}) as mock:
            result = provider.create_mr("feature", "main", title="My MR", description="desc")
        assert result["iid"] == 1
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["source_branch"] == "feature"
        assert data["remove_source_branch"] is True

    def test_create_mr_default_title(self, provider):
        with patch_api({"iid": 1}) as mock:
            provider.create_mr("feat", "main")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "Merge feat into main" in data["title"]

    def test_list_mrs(self, provider):
        with patch_api([{"iid": 1}, {"iid": 2}]):
            result = provider.list_mrs("opened")
        assert len(result) == 2

    def test_list_mrs_error(self, provider):
        with patch_api({"error": 500}):
            result = provider.list_mrs()
        assert result == []

    def test_get_mr(self, provider):
        with patch_api({"iid": 5, "title": "MR5"}):
            result = provider.get_mr(5)
        assert result["iid"] == 5

    def test_comment_on_mr_with_agent(self, provider):
        with patch_api({"id": 1}) as mock:
            provider.comment_on_mr(5, "looks good", agent_id="dev1")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "DEV1" in data["body"]
        assert "looks good" in data["body"]

    def test_comment_on_mr_no_agent(self, provider):
        with patch_api({"id": 1}) as mock:
            provider.comment_on_mr(5, "plain comment")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["body"] == "plain comment"

    def test_approve_mr(self, provider):
        with patch_api({"status": "ok"}) as mock:
            provider.approve_mr(5)
        assert "/merge_requests/5/approve" in str(mock.call_args)

    def test_merge_mr(self, provider):
        with patch_api({"state": "merged"}) as mock:
            result = provider.merge_mr(5, squash=True)
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["squash"] is True
        assert data["should_remove_source_branch"] is True

    def test_close_mr(self, provider):
        with patch_api({"state": "closed"}) as mock:
            provider.close_mr(5)
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["state_event"] == "close"

    def test_get_mr_changes(self, provider):
        with patch_api({"changes": []}):
            result = provider.get_mr_changes(5)
        assert "changes" in result

    def test_get_mr_approvals(self, provider):
        with patch_api({"approved": True}):
            result = provider.get_mr_approvals(5)
        assert result["approved"] is True

    def test_get_open_mrs_md_none(self, provider):
        with patch_api([]):
            md = provider.get_open_mrs_md()
        assert "none" in md

    def test_get_open_mrs_md_with_mrs(self, provider):
        mrs = [
            {
                "iid": 1,
                "title": "Feature X",
                "author": {"name": "Alice"},
                "source_branch": "feat-x",
                "target_branch": "main",
            }
        ]
        with patch_api(mrs):
            md = provider.get_open_mrs_md()
        assert "!1" in md
        assert "Feature X" in md
        assert "Alice" in md
        assert "feat-x" in md


# =============================================================================
# Backward-compatible / high-level methods
# =============================================================================

class TestBackwardCompat:
    def test_create_story(self, provider):
        with patch_api({"iid": 20, "title": "[STORY-001] Foo"}) as mock:
            result = provider.create_story("STORY-001", "Foo", "Description", priority="high")
        assert provider._issue_cache["STORY-001"] == 20
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "[STORY-001]" in data["title"]
        assert "priority::high" in data.get("labels", "")

    def test_create_story_no_iid(self, provider):
        with patch_api({"error": 422}):
            result = provider.create_story("STORY-002", "Bar", "Desc")
        assert "STORY-002" not in provider._issue_cache

    def test_create_sprint(self, provider):
        with patch_api({"id": 1, "title": "Sprint 1"}) as mock:
            result = provider.create_sprint(1, due_date="2025-12-31")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert data["title"] == "Sprint 1"
        assert data["due_date"] == "2025-12-31"

    def test_create_sprint_no_due_date(self, provider):
        with patch_api({"id": 2}) as mock:
            provider.create_sprint(2)
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "due_date" not in data

    def test_comment_alias(self, provider):
        with patch_api({"id": 1}):
            provider.comment(10, "dev1", "msg")

    def test_update_story_status_alias(self, provider):
        with patch_api({"iid": 10}):
            provider.update_story_status(10, "todo", "done")

    def test_close_story_alias(self, provider):
        with patch_api({"state": "closed"}):
            provider.close_story(10)

    def test_find_issue_by_story_id_alias(self, provider):
        provider._issue_cache["S-1"] = 99
        assert provider.find_issue_by_story_id("S-1") == 99

    def test_get_issue_notes_alias(self, provider):
        with patch_api([{"id": 1}]):
            result = provider.get_issue_notes(10, max_notes=5)
        assert len(result) == 1

    def test_comment_mr_alias(self, provider):
        with patch_api({"id": 1}):
            provider.comment_mr(5, "body", agent_id="tester")


# =============================================================================
# Error handling edge cases
# =============================================================================

class TestErrorHandling:
    @patch("opensepia.integrations.providers.gitlab.HTTPMixin._http_request_with_retry")
    def test_network_error(self, mock_http, provider):
        mock_http.return_value = {"error": "Connection refused"}
        result = provider.list_issues()
        assert result == []  # non-list falls through to empty

    @patch("opensepia.integrations.providers.gitlab.HTTPMixin._http_request_with_retry")
    def test_json_parse_error_in_http(self, mock_http, provider):
        mock_http.return_value = {"error": "Expecting value: line 1 column 1"}
        result = provider.search_issues("test")
        assert result == []

    def test_create_issue_no_labels(self, provider):
        with patch_api({"iid": 30}) as mock:
            provider.create_issue("T", "D")
        data = mock.call_args[1].get("data") or mock.call_args[0][3]
        assert "labels" not in data
