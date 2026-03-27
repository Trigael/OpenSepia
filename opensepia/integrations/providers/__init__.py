#!/usr/bin/env python3
"""
AI Dev Team — Provider Auto-Discovery
Detects the active board provider from environment variables.
"""

import os
import logging
from typing import Optional

from ..base import BoardProvider

logger = logging.getLogger(__name__)


def detect_provider() -> Optional[BoardProvider]:
    """
    Detect the active provider from env vars.

    Priority:
    1. Board Server — if BOARD_SERVER_URL is set (self-hosted, fastest)
    2. GitLab — if GITLAB_URL + GITLAB_TOKEN are set
    3. GitHub — if GITHUB_TOKEN + GITHUB_REPO are set
    """
    # Board Server (self-hosted)
    if os.getenv("BOARD_SERVER_URL"):
        from .boardserver import BoardServerProvider
        provider = BoardServerProvider()
        if provider.enabled:
            logger.debug("Board provider: Board Server (%s)", os.getenv("BOARD_SERVER_URL"))
            return provider

    # GitLab
    if os.getenv("GITLAB_URL") and os.getenv("GITLAB_TOKEN"):
        from .gitlab import GitLabProvider
        provider = GitLabProvider()
        if provider.enabled:
            logger.debug("Board provider: GitLab")
            return provider

    # GitHub
    if os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPO"):
        from .github import GitHubProvider
        provider = GitHubProvider()
        if provider.enabled:
            logger.debug("Board provider: GitHub")
            return provider

    # Markdown (local files — always available as fallback)
    from .markdown import MarkdownProvider
    try:
        from opensepia.config import OrchestratorConfig
        config = OrchestratorConfig.load()
        board_dir = config.board_dir
    except (ImportError, OSError, ValueError):
        board_dir = None
    provider = MarkdownProvider(board_dir=board_dir)
    if provider.enabled:
        logger.debug("Board provider: Markdown (local files)")
        return provider

    logger.warning("No board provider found")
    return None
