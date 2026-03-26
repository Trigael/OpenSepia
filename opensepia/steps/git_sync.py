"""
AI Dev Team — Git sync step.

Syncs workspace/src to a feature branch in the git repo and creates
a merge request via the provider API.
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

from opensepia.pipeline import PipelineContext
from opensepia.errors import GitSyncError

logger = logging.getLogger(__name__)


class GitSyncStep:
    """Sync workspace -> repo -> feature branch -> MR."""

    name = "git_sync"
    critical = False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.dry_run:
            return ctx

        repo_url = os.environ.get("GIT_REPO_URL", "")
        repo_path = Path(os.environ.get("GIT_REPO_PATH", str(ctx.project_dir / "repo")))
        git_token = os.environ.get("GIT_TOKEN", "")

        if not repo_url or not (repo_path / ".git").exists():
            print("  Git sync skipped (repo not configured or doesn't exist)")
            return ctx

        auth_url = re.sub(r"https://", f"https://oauth2:{git_token}@", repo_url)

        branch_name = self._compute_branch_name(ctx)
        timestamp = datetime.now().isoformat()

        print(f"  Git sync: workspace/src -> branch {branch_name}")

        try:
            self._sync_to_branch(ctx, repo_path, auth_url, branch_name, timestamp)
        except GitSyncError:
            raise
        except Exception as e:
            logger.warning("Git sync error: %s", e)
            print(f"  Git sync failed (non-critical): {e}")

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

    def _sync_to_branch(
        self,
        ctx: PipelineContext,
        repo_path: Path,
        auth_url: str,
        branch_name: str,
        timestamp: str,
    ) -> None:
        """Execute git operations: fetch, branch, rsync, commit, push."""

        def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
            # Sanitize output to prevent token leakage
            result = subprocess.run(
                ["git"] + list(args),
                capture_output=True,
                text=True,
                cwd=str(repo_path),
                timeout=60,
            )
            if check and result.returncode != 0:
                # Sanitize error output
                sanitized = re.sub(r"oauth2:[^@]*@", "oauth2:***@", result.stderr)
                raise GitSyncError(f"git {args[0]} failed: {sanitized}")
            return result

        # Fetch and reset to main
        run_git("fetch", auth_url, "main")
        run_git("checkout", "main", check=False)
        run_git("reset", "--hard", "FETCH_HEAD", check=False)

        # Create/switch to feature branch
        run_git("checkout", "-b", branch_name, check=False)

        # Rsync workspace/src -> repo/src
        src_dir = ctx.workspace_dir / "src"
        dest_dir = repo_path / "src"
        if src_dir.exists():
            subprocess.run(
                [
                    "rsync", "-a", "--delete",
                    "--exclude=.git", "--exclude=node_modules",
                    "--exclude=__pycache__", "--exclude=.venv",
                    "--exclude=venv", "--exclude=.claude",
                    f"{src_dir}/", f"{dest_dir}/",
                ],
                capture_output=True,
                cwd=str(repo_path),
                timeout=60,
            )

        # Stage and check for changes
        run_git("add", "src/")

        diff_result = run_git("diff", "--cached", "--quiet", check=False)
        if diff_result.returncode == 0:
            print("  Git: no changes to commit")
            run_git("checkout", "main", check=False)
            run_git("branch", "-D", branch_name, check=False)
            return

        # Get changed files for commit message
        changes_result = run_git("diff", "--cached", "--name-only", "--", "src/", check=False)
        code_changes = "\n".join(changes_result.stdout.strip().split("\n")[:5])

        # Build story slug for commit message
        story_slug = branch_name.split("/", 1)[1] if "/" in branch_name else ""

        if story_slug and not story_slug.startswith("sprint-"):
            commit_msg = f"feat({story_slug}): sprint {ctx.sprint_num} cycle {ctx.cycle_num}"
        else:
            commit_msg = f"feat: sprint {ctx.sprint_num} cycle {ctx.cycle_num}"

        commit_msg += f"\n\nAutomatic commit after AI Dev Team run.\nMode: {ctx.mode} | Time: {timestamp}"
        if code_changes:
            commit_msg += f"\n\nChanged files (code):\n{code_changes}"

        run_git("commit", "-m", commit_msg)

        # Push feature branch
        push_result = subprocess.run(
            ["git", "push", auth_url, branch_name, "--force"],
            capture_output=True,
            text=True,
            cwd=str(repo_path),
            timeout=120,
        )
        if push_result.returncode != 0:
            sanitized = re.sub(r"oauth2:[^@]*@", "oauth2:***@", push_result.stderr)
            logger.warning("Git push warning: %s", sanitized)

        print(f"  Git: pushed branch {branch_name}")

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
            print("  MR: missing configuration, skipping")
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
                print(f"  MR !{existing[0]['iid']} already exists — OK")
                return
        except Exception as e:
            print(f"  MR: error checking: {e}")
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
                print(f"  MR !{mr['iid']} created: {mr['web_url']}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"  MR error {e.code}: {body[:200]}")
        except Exception as e:
            print(f"  MR error: {e}")
