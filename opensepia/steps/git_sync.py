"""
AI Dev Team — Git sync step.

Commits workspace changes to a feature branch and creates a merge request.
The workspace (project/workspace/) is itself the git repo — no separate
repo/ folder or copy step needed.
"""

import os
import re
import json
import subprocess
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path

from opensepia import log
from opensepia.pipeline import PipelineContext
from opensepia.errors import GitSyncError

logger = logging.getLogger(__name__)


class GitSyncStep:
    """Commit workspace changes, push feature branch, create MR."""

    name = "git_sync"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        workspace = ctx.workspace_dir
        git_dir = workspace / ".git"

        if not workspace.exists():
            return ctx

        if not git_dir.exists():
            # Not an error — git is optional. Only log at debug level.
            logger.debug("Git sync skipped (workspace is not a git repo)")
            return ctx

        repo_url = os.environ.get("GIT_REPO_URL", "")
        git_token = os.environ.get("GIT_TOKEN", "")

        if not repo_url:
            logger.debug("Git sync skipped (GIT_REPO_URL not set)")
            return ctx

        auth_url = re.sub(r"https://", f"https://oauth2:{git_token}@", repo_url)
        branch_name = self._compute_branch_name(ctx)
        timestamp = datetime.now().isoformat()

        log.step("git_sync", f"Workspace -> branch {branch_name}")

        try:
            self._commit_and_push(ctx, workspace, auth_url, branch_name, timestamp)
        except GitSyncError:
            raise
        except Exception as e:
            logger.warning("Git sync error: %s", e)
            log.warn(f"Git sync failed (non-critical): {e}")

        return ctx

    def _compute_branch_name(self, ctx: PipelineContext) -> str:
        """Compute feature branch name from active story IDs."""
        story_slug = ""

        sprint_md_path = ctx.board_dir / "sprint.md"
        if sprint_md_path.exists():
            try:
                content = sprint_md_path.read_text(encoding="utf-8")
                stories = re.findall(
                    r"###\s+(STORY-\d+|BUG-\d+).*?\n\*\*Status\*\*:\s*(IN_PROGRESS|REVIEW|TESTING)",
                    content, re.DOTALL,
                )
                if stories:
                    ids = [s[0].lower().replace("-", "") for s in stories[:3]]
                    story_slug = "-".join(ids)
            except Exception:
                pass

        if story_slug:
            return f"ai-team/{story_slug}-s{ctx.sprint_num}c{ctx.cycle_num}"
        return f"ai-team/sprint-{ctx.sprint_num}-cycle-{ctx.cycle_num}"

    def _commit_and_push(
        self,
        ctx: PipelineContext,
        workspace: Path,
        auth_url: str,
        branch_name: str,
        timestamp: str,
    ) -> None:
        """Commit workspace changes, push branch, create MR."""

        def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
            result = subprocess.run(
                ["git"] + list(args),
                capture_output=True,
                text=True,
                cwd=str(workspace),
                timeout=60,
            )
            if check and result.returncode != 0:
                sanitized = re.sub(r"oauth2:[^@]*@", "oauth2:***@", result.stderr)
                raise GitSyncError(f"git {args[0]} failed: {sanitized}")
            return result

        # Fetch latest main and create feature branch from it
        run_git("fetch", auth_url, "main", check=False)
        run_git("checkout", "main", check=False)
        run_git("reset", "--hard", "FETCH_HEAD", check=False)
        run_git("checkout", "-b", branch_name, check=False)

        # Stage all code changes (src/, tests/, docs/, config/)
        run_git("add", "-A")

        # Check for changes
        diff_result = run_git("diff", "--cached", "--quiet", check=False)
        if diff_result.returncode == 0:
            log.step_detail("git_sync", "No changes to commit")
            run_git("checkout", "main", check=False)
            run_git("branch", "-D", branch_name, check=False)
            return

        # Get changed files for commit message
        changes_result = run_git("diff", "--cached", "--name-only", check=False)
        changed_files = changes_result.stdout.strip().split("\n")[:10]
        code_changes = "\n".join(changed_files)

        # Build commit message
        story_slug = branch_name.split("/", 1)[1] if "/" in branch_name else ""

        if story_slug and not story_slug.startswith("sprint-"):
            commit_msg = f"feat({story_slug}): sprint {ctx.sprint_num} cycle {ctx.cycle_num}"
        else:
            commit_msg = f"feat: sprint {ctx.sprint_num} cycle {ctx.cycle_num}"

        commit_msg += f"\n\nAutomatic commit after AI Dev Team run.\nMode: {ctx.mode} | Time: {timestamp}"
        if code_changes:
            commit_msg += f"\n\nChanged files:\n{code_changes}"

        run_git("commit", "-m", commit_msg)

        # Push feature branch
        push_result = subprocess.run(
            ["git", "push", auth_url, branch_name, "--force"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=120,
        )
        if push_result.returncode != 0:
            sanitized = re.sub(r"oauth2:[^@]*@", "oauth2:***@", push_result.stderr)
            logger.warning("Git push warning: %s", sanitized)

        log.step("git_sync", f"Pushed branch {branch_name}")

        # Create MR
        self._create_mr(ctx, branch_name, code_changes)

        # Return to main
        run_git("checkout", "main", check=False)

    def _create_mr(self, ctx: PipelineContext, branch_name: str, code_changes: str) -> None:
        """Create merge request via provider API."""
        url = os.environ.get("GITLAB_URL", "")
        token = os.environ.get("GITLAB_TOKEN", "")
        project = os.environ.get("GITLAB_PROJECT_ID", "")

        if not all([url, token, project]):
            log.step_detail("git_sync", "MR: missing configuration, skipping")
            return

        encoded_project = urllib.parse.quote(project, safe="")
        api_base = f"{url}/api/v4/projects/{encoded_project}"

        # Check for existing MR
        try:
            check_url = f"{api_base}/merge_requests?source_branch={urllib.parse.quote(branch_name)}&state=opened"
            req = urllib.request.Request(check_url, headers={"PRIVATE-TOKEN": token})
            with urllib.request.urlopen(req, timeout=15) as resp:
                existing = json.loads(resp.read())
            if existing:
                log.step_detail("git_sync", f"MR !{existing[0]['iid']} already exists — OK")
                return
        except Exception as e:
            log.warn(f"MR: error checking: {e}")
            return

        # Create new MR
        story_slug = branch_name.split("/", 1)[1] if "/" in branch_name else f"sprint-{ctx.sprint_num}"
        mr_data = json.dumps({
            "source_branch": branch_name,
            "target_branch": "main",
            "title": f"AI Team: {story_slug} (S{ctx.sprint_num}C{ctx.cycle_num})",
            "description": (
                f"## AI Dev Team — automatic MR\n\n"
                f"**Sprint**: {ctx.sprint_num} | **Cycle**: {ctx.cycle_num} | **Mode**: {ctx.mode}\n\n"
                f"### Code changes\n{code_changes}\n\n---\n"
                f"*Created automatically by the ai-team orchestrator.*\n"
            ),
            "remove_source_branch": True,
        }).encode()

        req = urllib.request.Request(
            f"{api_base}/merge_requests",
            data=mr_data,
            method="POST",
            headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                mr = json.loads(resp.read())
                log.step("git_sync", f"MR !{mr['iid']} created: {mr['web_url']}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.error(f"MR error {e.code}: {body[:200]}")
        except Exception as e:
            log.error(f"MR error: {e}")
