"""
AI Dev Team — Over-Generalization Detection & Agent Splitting.

Analyzes agent behavior to detect when an agent handles too many
domains, and proposes splitting into specialists.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Technology domain clusters for generalization detection
DOMAIN_CLUSTERS: dict[str, set[str]] = {
    "frontend": {"react", "vue", "angular", "css", "html", "tailwind", "htmx", "javascript", "typescript", "jsx", "tsx", "component", "ui", "ux"},
    "backend": {"fastapi", "flask", "django", "express", "api", "endpoint", "router", "middleware", "rest", "graphql", "server"},
    "database": {"sql", "sqlite", "postgresql", "mysql", "migration", "schema", "orm", "sqlalchemy", "query", "index", "table"},
    "devops": {"docker", "dockerfile", "compose", "nginx", "kubernetes", "ci", "cd", "deploy", "container", "registry"},
    "testing": {"pytest", "unittest", "test", "mock", "fixture", "coverage", "e2e", "integration"},
    "security": {"auth", "jwt", "oauth", "cors", "csrf", "xss", "injection", "middleware", "encryption", "hash"},
}

# Threshold for triggering a split proposal
SPLIT_THRESHOLD = 0.6


@dataclass
class SplitProposal:
    """Proposal to split an over-generalized agent."""
    original_id: str
    into: list[dict[str, str]]  # [{id, name, prompt_focus}, ...]
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


class AgentSplitter:
    """Detects over-generalization and proposes agent splitting."""

    def __init__(self, board_dir: Path):
        self.board_dir = board_dir

    def analyze_generalization(
        self,
        agent_id: str,
        memory_content: str,
        recent_results: list[dict[str, Any]],
    ) -> SplitProposal | None:
        """Analyze if an agent is handling too many domains.

        Returns a SplitProposal if over-generalization detected, else None.
        """
        scores: dict[str, float] = {}
        detected_domains: dict[str, int] = {}

        # 1. Domain diversity in memory (weight: 0.3)
        memory_domains = self._detect_domains(memory_content)
        domain_count = len(memory_domains)
        scores["memory_domains"] = min(domain_count / 3.0, 1.0) * 0.3
        detected_domains.update(memory_domains)

        # 2. File path dispersion in recent responses (weight: 0.3)
        path_dirs = set()
        for result in recent_results:
            response = result.get("response", "")
            # Extract file paths from ---FILES--- sections
            paths = re.findall(r'path:\s*(\S+)', response)
            for p in paths:
                parts = p.split("/")
                if len(parts) >= 2:
                    path_dirs.add(parts[0] + "/" + parts[1])
        dir_count = len(path_dirs)
        scores["path_dispersion"] = min(dir_count / 4.0, 1.0) * 0.3

        # 3. Self-reported overload (weight: 0.2)
        overload_keywords = [
            "too many responsibilities", "outside my expertise",
            "handling too much", "not my area", "unfamiliar with",
            "struggling with", "need a specialist",
        ]
        overload_score = 0.0
        for result in recent_results:
            response = result.get("response", "").lower()
            for kw in overload_keywords:
                if kw in response:
                    overload_score = 1.0
                    break
        scores["self_reported"] = overload_score * 0.2

        # 4. Task completion issues (weight: 0.2)
        blocked_count = sum(
            1 for r in recent_results
            if "BLOCKED" in r.get("response", "") or r.get("error")
        )
        if recent_results:
            scores["blocked_rate"] = min(blocked_count / max(len(recent_results), 1), 1.0) * 0.2
        else:
            scores["blocked_rate"] = 0.0

        total_score = sum(scores.values())

        if total_score >= SPLIT_THRESHOLD:
            # Generate split proposal based on detected domains
            top_domains = sorted(detected_domains.items(), key=lambda x: x[1], reverse=True)[:3]
            if len(top_domains) < 2:
                return None  # Need at least 2 domains to split

            split_into = []
            for domain, _count in top_domains[:2]:
                child_id = f"{agent_id}_{domain}"
                split_into.append({
                    "id": child_id,
                    "name": f"{domain.title()} Specialist",
                    "prompt_focus": f"Specializing in {domain} tasks",
                })

            return SplitProposal(
                original_id=agent_id,
                into=split_into,
                reason=f"Agent handles {domain_count}+ domains (score: {total_score:.2f})",
                metrics={
                    "scores": scores,
                    "total_score": total_score,
                    "detected_domains": dict(detected_domains),
                    "path_dirs": list(path_dirs),
                },
            )

        return None

    def _detect_domains(self, text: str) -> dict[str, int]:
        """Detect technology domains mentioned in text.

        Returns dict of domain -> mention count.
        """
        text_lower = text.lower()
        words = set(re.findall(r'\b[a-z]+\b', text_lower))

        domains: dict[str, int] = {}
        for domain, keywords in DOMAIN_CLUSTERS.items():
            matches = words & keywords
            if matches:
                domains[domain] = len(matches)

        return domains

    def propose_split(
        self,
        proposal: SplitProposal,
        sprint: int,
        cycle: int,
    ) -> Path:
        """Create a split proposal file."""
        import yaml
        from datetime import datetime

        proposals_dir = self.board_dir / "evolution" / "proposals" / "pending"
        proposals_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{proposal.original_id}_split.yaml"
        path = proposals_dir / filename

        data = {
            "type": "split_agent",
            "proposed_by": "system",
            "proposed_at": datetime.now().isoformat(),
            "sprint": sprint,
            "cycle": cycle,
            "status": "pending",
            "details": {
                "original_id": proposal.original_id,
                "into": proposal.into,
                "reason": proposal.reason,
                "metrics": proposal.metrics,
            },
        }

        path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info("Split proposal created for %s: %s", proposal.original_id, filename)
        return path
