"""Mock integration test — runs full pipeline cycles with canned agent responses.

No Claude API calls. Real git, real board adapter, real pipeline.
Tests the per-story branch workflow end-to-end across multiple cycles.
"""

import subprocess
import logging
import time
import re
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

from opensepia.pipeline import Pipeline, PipelineContext
from opensepia.board_adapter_markdown import MarkdownBoardAdapter
from opensepia.commands.run import build_pipeline
from opensepia.agents.invoker import AgentResult

logger = logging.getLogger(__name__)


# =============================================================================
# Canned agent responses — simulate a realistic multi-cycle dev team
# =============================================================================

CYCLE_1_RESPONSES = {
    "po": """## PO Decisions [cycle 1]

Reviewed sprint backlog. Prioritizing STORY-001 and STORY-002 for this sprint.

## Messages for team

---FILES---
path: board/sprint.md
content:
# Sprint 1

## TODO
- [ ] STORY-003: API documentation

## IN PROGRESS
- [ ] STORY-001: User authentication (dev1)
- [ ] STORY-002: Database schema (dev2)

## REVIEW

## TESTING

## DONE

## BLOCKED
---
path: board/standup.md
action: append
content:
## 🟣 Product Owner
- **Done**: Sprint planning, story prioritization
- **Doing**: Monitoring STORY-001 and STORY-002
- **Blockers**: none
---
path: board/inbox/dev1.md
action: append
content:
## Message from Product Owner — Sprint 1, Cycle 1
Please start STORY-001: User authentication. Focus on login/logout endpoints.
---
path: board/inbox/dev2.md
action: append
content:
## Message from Product Owner — Sprint 1, Cycle 1
Please start STORY-002: Database schema. Set up SQLAlchemy models.
---END---
""",
    "pm": """## Sprint Update [cycle 1]

Assigned stories to developers.

## Tasks for team:
- dev1: STORY-001 (User authentication)
- dev2: STORY-002 (Database schema)
- devops: Prepare Docker setup
- tester: Review test plan

---FILES---
path: board/standup.md
action: append
content:
## 🔵 Project Manager
- **Done**: Assigned STORY-001 to dev1, STORY-002 to dev2
- **Doing**: Tracking sprint progress
- **Blockers**: none
---
path: board/inbox/dev1.md
action: append
content:
## Message from PM — Sprint 1, Cycle 1
You're assigned STORY-001: User authentication. Coordinate with dev2 on the DB layer.
---
path: board/inbox/dev2.md
action: append
content:
## Message from PM — Sprint 1, Cycle 1
You're assigned STORY-002: Database schema. Dev1 will need the User model for auth.
---END---
""",
    "dev1": """## Dev1 Report [cycle 1]

Implementing STORY-001: User authentication.
Created login and logout endpoints with JWT token support.

---FILES---
path: board/standup.md
action: append
content:
## 🟢 Developer 1
- **Done**: Implemented login/logout endpoints for STORY-001
- **Doing**: Adding JWT token validation
- **Blockers**: none
---
path: workspace/src/auth.py
content:
\"\"\"Authentication module — STORY-001.\"\"\"
import hashlib
import secrets

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(password: str, stored: str) -> bool:
    salt, hashed = stored.split(":")
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == hashed

def create_token(user_id: str) -> str:
    return secrets.token_urlsafe(32)
---
path: workspace/src/routes_auth.py
content:
\"\"\"Auth routes — STORY-001.\"\"\"
from auth import hash_password, verify_password, create_token

def login(username: str, password: str) -> dict:
    # In real app, look up user from DB
    token = create_token(username)
    return {"token": token, "user": username}

def logout(token: str) -> dict:
    return {"status": "logged_out"}
---
path: workspace/tests/test_auth.py
content:
\"\"\"Tests for auth module — STORY-001.\"\"\"
from auth import hash_password, verify_password, create_token

def test_hash_and_verify():
    hashed = hash_password("secret123")
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)

def test_create_token():
    token = create_token("user1")
    assert len(token) > 20
---
path: board/sprint.md
content:
# Sprint 1

## TODO
- [ ] STORY-003: API documentation

## IN PROGRESS
- [ ] STORY-002: Database schema (dev2)

## REVIEW
- [ ] STORY-001: User authentication (dev1)

## TESTING

## DONE

## BLOCKED
---
path: board/inbox/dev2.md
action: append
content:
## Message from Dev1 — Sprint 1, Cycle 1
STORY-001 is ready for code review. Please check workspace/src/auth.py and routes_auth.py.
---
path: board/inbox/tester.md
action: append
content:
## Message from Dev1 — Sprint 1, Cycle 1
STORY-001: User authentication is in REVIEW. Ready for QA when code review passes.
---END---
""",
    "dev2": """## Dev2 Report [cycle 1]

Implementing STORY-002: Database schema.
Created SQLAlchemy models for User and Session.

---FILES---
path: board/standup.md
action: append
content:
## 🟩 Developer 2
- **Done**: Created User and Session models for STORY-002
- **Doing**: Adding migration scripts
- **Blockers**: none
---
path: workspace/src/models.py
content:
\"\"\"Database models — STORY-002.\"\"\"

class User:
    def __init__(self, username: str, email: str, password_hash: str):
        self.username = username
        self.email = email
        self.password_hash = password_hash

class Session:
    def __init__(self, user_id: str, token: str):
        self.user_id = user_id
        self.token = token
        self.active = True
---
path: workspace/src/db.py
content:
\"\"\"Database connection — STORY-002.\"\"\"
import sqlite3
from pathlib import Path

DB_PATH = Path("data/app.db")

def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(str(DB_PATH))

def init_db():
    conn = get_connection()
    conn.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
    \"\"\")
    conn.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    \"\"\")
    conn.commit()
    conn.close()
---
path: workspace/tests/test_models.py
content:
\"\"\"Tests for models — STORY-002.\"\"\"
from models import User, Session

def test_user_creation():
    u = User("alice", "alice@example.com", "hash123")
    assert u.username == "alice"
    assert u.email == "alice@example.com"

def test_session_creation():
    s = Session("alice", "token_abc")
    assert s.active is True
---
path: board/inbox/dev1.md
action: append
content:
## Message from Dev2 — Sprint 1, Cycle 1
STORY-002 models are ready. Please review workspace/src/models.py and db.py.
---END---
""",
    "devops": """## DevOps Report [cycle 1]

Setting up Docker environment.

---FILES---
path: board/standup.md
action: append
content:
## 🟠 DevOps Engineer
- **Done**: Created Dockerfile and docker-compose.yml
- **Doing**: Adding healthcheck
- **Blockers**: none
---
path: workspace/Dockerfile
content:
FROM python:3.11-slim
WORKDIR /app
COPY src/ ./src/
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["python", "-m", "src.main"]
---
path: workspace/docker-compose.yml
content:
version: "3.8"
services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
---END---
""",
    "tester": """## QA Report [cycle 1]

Reviewing STORY-001 authentication implementation.

---FILES---
path: board/standup.md
action: append
content:
## 🔴 QA Engineer
- **Done**: Reviewed STORY-001 auth module
- **Doing**: Writing additional test cases
- **Blockers**: none
---
path: board/inbox/dev1.md
action: append
content:
## 🔴 QA Functional Review — STORY-001

**Story:** STORY-001: User authentication

**Acceptance criteria:**
- [x] Login endpoint works
- [x] Logout endpoint works
- [x] Password hashing implemented
- [ ] Missing: token expiration

**Tests:**
- [x] Hash and verify test
- [x] Token creation test
- [ ] Missing: test for invalid credentials

**Verdict:** NEEDS CHANGES — add token expiration
---END---
""",
}

CYCLE_2_RESPONSES = {
    "po": """## PO Decisions [cycle 2]

STORY-002 looks complete. Moving to DONE.
STORY-001 needs minor changes per QA feedback.

---FILES---
path: board/sprint.md
content:
# Sprint 1

## TODO
- [ ] STORY-003: API documentation

## IN PROGRESS
- [ ] STORY-001: User authentication (dev1)

## REVIEW

## TESTING

## DONE
- [x] STORY-002: Database schema (dev2)

## BLOCKED
---
path: board/standup.md
action: append
content:
## 🟣 Product Owner
- **Done**: Accepted STORY-002
- **Doing**: Reviewing STORY-001 QA feedback
- **Blockers**: none
---END---
""",
    "pm": """## Sprint Update [cycle 2]

STORY-002 completed and accepted by PO.
STORY-001 back to dev1 for QA fixes.

---FILES---
path: board/standup.md
action: append
content:
## 🔵 Project Manager
- **Done**: Tracked STORY-002 completion
- **Doing**: Following up on STORY-001 QA feedback
- **Blockers**: none
---
path: board/inbox/dev1.md
action: append
content:
## Message from PM — Sprint 1, Cycle 2
QA found issues with STORY-001. Please add token expiration and invalid credentials test.
---END---
""",
    "dev1": """## Dev1 Report [cycle 2]

Fixing STORY-001 per QA feedback. Added token expiration.

---FILES---
path: board/standup.md
action: append
content:
## 🟢 Developer 1
- **Done**: Added token expiration to STORY-001
- **Doing**: Updating tests
- **Blockers**: none
---
path: workspace/src/auth.py
content:
\"\"\"Authentication module — STORY-001 (updated with expiration).\"\"\"
import hashlib
import secrets
import time

TOKEN_EXPIRY = 3600  # 1 hour

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(password: str, stored: str) -> bool:
    salt, hashed = stored.split(":")
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == hashed

def create_token(user_id: str) -> dict:
    token = secrets.token_urlsafe(32)
    return {"token": token, "expires_at": time.time() + TOKEN_EXPIRY}

def is_token_valid(token_data: dict) -> bool:
    return time.time() < token_data.get("expires_at", 0)
---
path: workspace/tests/test_auth.py
content:
\"\"\"Tests for auth module — STORY-001.\"\"\"
from auth import hash_password, verify_password, create_token, is_token_valid

def test_hash_and_verify():
    hashed = hash_password("secret123")
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)

def test_create_token():
    token_data = create_token("user1")
    assert "token" in token_data
    assert "expires_at" in token_data

def test_token_expiry():
    token_data = create_token("user1")
    assert is_token_valid(token_data)
    token_data["expires_at"] = 0
    assert not is_token_valid(token_data)
---
path: board/sprint.md
content:
# Sprint 1

## TODO
- [ ] STORY-003: API documentation

## IN PROGRESS

## REVIEW
- [ ] STORY-001: User authentication (dev1)

## TESTING

## DONE
- [x] STORY-002: Database schema (dev2)

## BLOCKED
---
path: board/inbox/tester.md
action: append
content:
## Message from Dev1 — Sprint 1, Cycle 2
STORY-001 updated with token expiration. Ready for re-review.
---END---
""",
    "dev2": """## Dev2 Report [cycle 2]

Reviewed dev1's STORY-001 code. Looks good.

---FILES---
path: board/standup.md
action: append
content:
## 🟩 Developer 2
- **Done**: Code review of STORY-001
- **Doing**: Looking at STORY-003
- **Blockers**: none
---
path: board/inbox/dev1.md
action: append
content:
## Code Review from Dev2 — STORY-001
Code looks clean. Auth module is well structured. Token expiration fix is good.
Approved.
---END---
""",
    "devops": """## DevOps Report [cycle 2]

Added healthcheck to Docker setup.

---FILES---
path: board/standup.md
action: append
content:
## 🟠 DevOps Engineer
- **Done**: Added healthcheck to Dockerfile
- **Doing**: Testing docker-compose
- **Blockers**: none
---END---
""",
    "tester": """## QA Report [cycle 2]

Re-reviewed STORY-001 with fixes. All criteria now met.

---FILES---
path: board/standup.md
action: append
content:
## 🔴 QA Engineer
- **Done**: Re-reviewed STORY-001, all tests pass
- **Doing**: Preparing test plan for STORY-003
- **Blockers**: none
---
path: board/inbox/dev1.md
action: append
content:
## 🔴 QA Functional Review — STORY-001 (re-review)

**Story:** STORY-001: User authentication

**Acceptance criteria:**
- [x] Login endpoint works
- [x] Logout endpoint works
- [x] Password hashing implemented
- [x] Token expiration added

**Tests:**
- [x] Hash and verify
- [x] Token creation with expiry
- [x] Token expiry validation

**Verdict:** APPROVED
---
path: board/inbox/po.md
action: append
content:
## Message from QA — Sprint 1, Cycle 2
STORY-001: User authentication has passed functional review. Ready for PO acceptance.
---END---
""",
}

CYCLE_3_RESPONSES = {
    "po": """## PO Decisions [cycle 3]

STORY-001 passed QA. Accepting and moving to DONE.
Starting STORY-003.

---FILES---
path: board/sprint.md
content:
# Sprint 1

## TODO

## IN PROGRESS
- [ ] STORY-003: API documentation (dev2)

## REVIEW

## TESTING

## DONE
- [x] STORY-001: User authentication (dev1)
- [x] STORY-002: Database schema (dev2)

## BLOCKED
---
path: board/standup.md
action: append
content:
## 🟣 Product Owner
- **Done**: Accepted STORY-001, assigned STORY-003
- **Doing**: Sprint review
- **Blockers**: none
---END---
""",
    "pm": """## Sprint Update [cycle 3]

Sprint going well. 2 of 3 stories done. STORY-003 assigned to dev2.

---FILES---
path: board/standup.md
action: append
content:
## 🔵 Project Manager
- **Done**: Updated sprint status
- **Doing**: Coordinating STORY-003
- **Blockers**: none
---END---
""",
    "dev1": """## Dev1 Report [cycle 3]

STORY-001 accepted. Helping dev2 with STORY-003 API docs review.

---FILES---
path: board/standup.md
action: append
content:
## 🟢 Developer 1
- **Done**: STORY-001 accepted by PO
- **Doing**: Reviewing STORY-003 progress
- **Blockers**: none
---END---
""",
    "dev2": """## Dev2 Report [cycle 3]

Starting STORY-003: API documentation.

---FILES---
path: board/standup.md
action: append
content:
## 🟩 Developer 2
- **Done**: Started STORY-003 API docs
- **Doing**: Writing endpoint documentation
- **Blockers**: none
---
path: workspace/docs/api.md
content:
# API Documentation — STORY-003

## Authentication

### POST /auth/login
Login with username and password. Returns JWT token.

### POST /auth/logout
Invalidate current session token.

## Database

### Models
- User: username, email, password_hash
- Session: token, user_id, active
---END---
""",
    "devops": """## DevOps Report [cycle 3]

Docker setup stable. No changes needed.

---FILES---
path: board/standup.md
action: append
content:
## 🟠 DevOps Engineer
- **Done**: Docker setup verified
- **Doing**: Monitoring
- **Blockers**: none
---END---
""",
    "tester": """## QA Report [cycle 3]

No stories in testing. Waiting for STORY-003.

---FILES---
path: board/standup.md
action: append
content:
## 🔴 QA Engineer
- **Done**: Test plan for STORY-003
- **Doing**: Waiting for implementation
- **Blockers**: none
---END---
""",
}

ALL_CYCLES = [CYCLE_1_RESPONSES, CYCLE_2_RESPONSES, CYCLE_3_RESPONSES]


# =============================================================================
# Test infrastructure
# =============================================================================

def _setup_project(tmp_path):
    """Create a realistic project structure."""
    board = tmp_path / "board"
    board.mkdir()
    (board / "inbox").mkdir()
    (board / "archive").mkdir()

    (board / "sprint.md").write_text(
        "# Sprint 1\n\n## TODO\n"
        "- [ ] STORY-001: User authentication\n"
        "- [ ] STORY-002: Database schema\n"
        "- [ ] STORY-003: API documentation\n\n"
        "## IN PROGRESS\n\n## REVIEW\n\n## TESTING\n\n## DONE\n\n## BLOCKED\n",
        encoding="utf-8",
    )
    (board / "backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (board / "project.md").write_text("# Mock Project\n\nA test project for integration testing.\n", encoding="utf-8")
    (board / "standup.md").write_text("", encoding="utf-8")
    (board / "decisions.md").write_text("# Decisions\n", encoding="utf-8")

    for agent in ["po", "pm", "dev1", "dev2", "devops", "tester"]:
        (board / "inbox" / f"{agent}.md").write_text("", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "docs").mkdir()

    # Initialize git
    _git(workspace, "init")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "config", "user.email", "test@test.com")
    (workspace / ".gitignore").write_text("__pycache__/\n*.pyc\ndata/\n", encoding="utf-8")
    (workspace / "README.md").write_text("# Mock Project\n", encoding="utf-8")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "Initial commit")

    # Config
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    logs_dir = tmp_path / "logs" / "runs"
    logs_dir.mkdir(parents=True)

    return board, workspace, config_dir, logs_dir


def _git(workspace, *args):
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True,
        cwd=str(workspace), timeout=10,
    )


def _make_agents_config():
    """Minimal agents config for testing."""
    return {
        "agents": {
            "po": {"name": "Product Owner", "color": "🟣", "system_prompt": "PO."},
            "pm": {"name": "Project Manager", "color": "🔵", "system_prompt": "PM."},
            "dev1": {"name": "Developer 1", "color": "🟢", "system_prompt": "Dev1."},
            "dev2": {"name": "Developer 2", "color": "🟩", "system_prompt": "Dev2."},
            "devops": {"name": "DevOps Engineer", "color": "🟠", "system_prompt": "DevOps."},
            "tester": {"name": "QA Engineer", "color": "🔴", "system_prompt": "Tester."},
        },
        "global": {},
        "execution": {"timeout": 30, "max_retries": 0, "retry_delay": 5, "pause_between_agents": 0},
    }


def _make_context(tmp_path, board, workspace, config_dir, logs_dir, agents_config, agent_ids, sprint_num=1, cycle_num=1):
    """Build a PipelineContext."""
    adapter = MarkdownBoardAdapter(
        board_dir=board, workspace_dir=workspace, project_dir=tmp_path,
    )
    return PipelineContext(
        mode="dev-team",
        tool_dir=tmp_path,
        project_dir=tmp_path,
        agents_config=agents_config,
        project_config={"sprint": {"current_sprint": sprint_num, "current_cycle": cycle_num}, "project": {"name": "Mock Project"}},
        board_dir=board,
        workspace_dir=workspace,
        config_dir=config_dir,
        logs_dir=logs_dir,
        sprint_num=sprint_num,
        cycle_num=cycle_num,
        agent_ids=agent_ids,
        board_adapter=adapter,
    )


def _mock_invoke(cycle_responses):
    """Create a mock invoke_agent that returns canned responses."""
    def _invoke(agent_id, context, base_dir, agent_name="", timeout=900, verbose=False):
        response = cycle_responses.get(agent_id, f"## {agent_id} Report\nNo work this cycle.\n---FILES---\n---END---")
        return AgentResult(
            agent_id=agent_id,
            agent_name=agent_name or agent_id,
            response=response,
            timestamp=datetime.now().isoformat(),
            context_size=len(context),
            response_size=len(response),
        )
    return _invoke


def _get_branches(workspace):
    result = _git(workspace, "branch", "--list")
    return [b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()]


def _get_log(workspace, branch="master", n=20):
    result = _git(workspace, "log", branch, f"--oneline", f"-{n}")
    return result.stdout.strip()


# =============================================================================
# Tests
# =============================================================================

class TestMockCycles:
    """Run full pipeline cycles with mocked agent responses."""

    def test_single_cycle(self, tmp_path):
        """Cycle 1: agents create code, commits land on story branches."""
        board, ws, cfg, logs = _setup_project(tmp_path)
        agents_config = _make_agents_config()
        agent_ids = ["po", "pm", "dev1", "dev2", "devops", "tester"]

        ctx = _make_context(tmp_path, board, ws, cfg, logs, agents_config, agent_ids)
        pipeline = build_pipeline(agents_config, agent_ids=agent_ids)

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=_mock_invoke(CYCLE_1_RESPONSES)):
            ctx = pipeline.run(ctx)

        # Story branches should exist
        branches = _get_branches(ws)
        assert "story/story-001" in branches, f"Expected story/story-001 in {branches}"
        assert "story/story-002" in branches, f"Expected story/story-002 in {branches}"

        # Check commits exist on story branches
        log_s1 = _get_log(ws, "story/story-001")
        assert "dev1" in log_s1.lower(), f"Expected dev1 commit on story/story-001: {log_s1}"

        log_s2 = _get_log(ws, "story/story-002")
        assert "dev2" in log_s2.lower(), f"Expected dev2 commit on story/story-002: {log_s2}"

        # Should be back on master
        current = _git(ws, "branch", "--show-current").stdout.strip()
        assert current == "master"

        print(f"\n--- Cycle 1 Results ---")
        print(f"Branches: {branches}")
        print(f"Agent results: {len(ctx.agent_results)}")
        print(f"Errors: {ctx.errors}")

    def test_three_cycles_story_lifecycle(self, tmp_path):
        """Full lifecycle: create branches, work on stories, merge on DONE."""
        board, ws, cfg, logs = _setup_project(tmp_path)
        agents_config = _make_agents_config()
        agent_ids = ["po", "pm", "dev1", "dev2", "devops", "tester"]

        print("\n" + "=" * 60)
        print("MOCK INTEGRATION TEST — 3 cycles, 6 agents")
        print("=" * 60)

        for cycle_num, cycle_responses in enumerate(ALL_CYCLES, start=1):
            print(f"\n--- Cycle {cycle_num} ---")
            ctx = _make_context(tmp_path, board, ws, cfg, logs, agents_config, agent_ids,
                                sprint_num=1, cycle_num=cycle_num)

            pipeline = build_pipeline(agents_config, agent_ids=agent_ids)

            with patch("opensepia.steps.agent_step.invoke_agent", side_effect=_mock_invoke(cycle_responses)):
                ctx = pipeline.run(ctx)

            branches = _get_branches(ws)
            master_log = _get_log(ws, "master")

            print(f"  Branches: {branches}")
            print(f"  Agent results: {len(ctx.agent_results)}")
            print(f"  Errors: {ctx.errors}")
            print(f"  Master log:\n    " + master_log.replace("\n", "\n    "))

        # After cycle 3:
        # - STORY-001 moved to DONE in cycle 3 → should be merged to master
        # - STORY-002 moved to DONE in cycle 2 → should be merged to master
        # - STORY-003 is IN PROGRESS → branch may or may not exist

        branches = _get_branches(ws)
        master_log = _get_log(ws, "master")

        print(f"\n--- Final State ---")
        print(f"Branches: {branches}")
        print(f"Master log:\n  " + master_log.replace("\n", "\n  "))

        # DONE stories should be merged (branches deleted)
        assert "story/story-002" not in branches, \
            f"STORY-002 is DONE — branch should be merged and deleted. Branches: {branches}"
        assert "story/story-001" not in branches, \
            f"STORY-001 is DONE — branch should be merged and deleted. Branches: {branches}"

        # Merge commits should appear on master
        assert "story-002" in master_log.lower() or "merge" in master_log.lower(), \
            f"Expected merge of STORY-002 on master. Log: {master_log}"

        # Workspace files should exist on master
        assert (ws / "src" / "auth.py").exists(), "auth.py should be on master after merge"
        assert (ws / "src" / "models.py").exists(), "models.py should be on master after merge"

    def test_no_api_calls(self, tmp_path):
        """Verify no real Claude CLI calls are made."""
        board, ws, cfg, logs = _setup_project(tmp_path)
        agents_config = _make_agents_config()
        agent_ids = ["po", "dev1"]

        ctx = _make_context(tmp_path, board, ws, cfg, logs, agents_config, agent_ids)
        pipeline = build_pipeline(agents_config, agent_ids=agent_ids)

        call_count = 0
        original_mock = _mock_invoke(CYCLE_1_RESPONSES)

        def counting_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_mock(*args, **kwargs)

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=counting_mock):
            ctx = pipeline.run(ctx)

        assert call_count == 2, f"Expected 2 agent calls, got {call_count}"
        assert len(ctx.agent_results) == 2

    def test_git_history_integrity(self, tmp_path):
        """After all cycles, git history should be clean and consistent."""
        board, ws, cfg, logs = _setup_project(tmp_path)
        agents_config = _make_agents_config()
        agent_ids = ["po", "pm", "dev1", "dev2", "devops", "tester"]

        for cycle_num, cycle_responses in enumerate(ALL_CYCLES, start=1):
            ctx = _make_context(tmp_path, board, ws, cfg, logs, agents_config, agent_ids,
                                sprint_num=1, cycle_num=cycle_num)
            pipeline = build_pipeline(agents_config, agent_ids=agent_ids)
            with patch("opensepia.steps.agent_step.invoke_agent", side_effect=_mock_invoke(cycle_responses)):
                ctx = pipeline.run(ctx)

        # Verify no detached HEAD or broken refs
        result = _git(ws, "fsck", "--no-dangling")
        assert result.returncode == 0, f"Git fsck failed: {result.stderr}"

        # Verify we're on master
        current = _git(ws, "branch", "--show-current").stdout.strip()
        assert current == "master"

        # Verify master has the merged content
        result = _git(ws, "log", "master", "--oneline")
        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) >= 3, f"Expected at least 3 commits on master, got {len(lines)}"

    def test_agent_author_attribution(self, tmp_path):
        """Commits should have the correct agent as author."""
        board, ws, cfg, logs = _setup_project(tmp_path)
        agents_config = _make_agents_config()
        agent_ids = ["po", "pm", "dev1", "dev2", "devops", "tester"]

        ctx = _make_context(tmp_path, board, ws, cfg, logs, agents_config, agent_ids)
        pipeline = build_pipeline(agents_config, agent_ids=agent_ids)

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=_mock_invoke(CYCLE_1_RESPONSES)):
            ctx = pipeline.run(ctx)

        # Check story/story-001 has dev1 as author
        result = _git(ws, "log", "story/story-001", "--format=%an", "-1")
        assert "Developer 1" in result.stdout, f"Expected Developer 1 as author, got: {result.stdout}"

        # Check story/story-002 has dev2 as author
        result = _git(ws, "log", "story/story-002", "--format=%an", "-1")
        assert "Developer 2" in result.stdout, f"Expected Developer 2 as author, got: {result.stdout}"

    def test_workspace_files_on_branch(self, tmp_path):
        """Files written by agents should be on the correct story branch."""
        board, ws, cfg, logs = _setup_project(tmp_path)
        agents_config = _make_agents_config()
        agent_ids = ["po", "pm", "dev1", "dev2", "devops", "tester"]

        ctx = _make_context(tmp_path, board, ws, cfg, logs, agents_config, agent_ids)
        pipeline = build_pipeline(agents_config, agent_ids=agent_ids)

        with patch("opensepia.steps.agent_step.invoke_agent", side_effect=_mock_invoke(CYCLE_1_RESPONSES)):
            ctx = pipeline.run(ctx)

        # Check files exist on story branches
        _git(ws, "checkout", "story/story-001")
        assert (ws / "src" / "auth.py").exists(), "auth.py should be on story/story-001"
        assert (ws / "src" / "routes_auth.py").exists(), "routes_auth.py should be on story/story-001"

        _git(ws, "checkout", "story/story-002")
        assert (ws / "src" / "models.py").exists(), "models.py should be on story/story-002"
        assert (ws / "src" / "db.py").exists(), "db.py should be on story/story-002"

        _git(ws, "checkout", "master")
