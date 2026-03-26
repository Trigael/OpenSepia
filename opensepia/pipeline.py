"""
AI Dev Team — Pipeline runner.

Defines the Step protocol and Pipeline class that executes steps
sequentially with structured error handling.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from opensepia.errors import OrchestratorError

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Shared mutable state flowing through the pipeline.

    Each step reads from and writes to this context, allowing
    subsequent steps to react to earlier results.
    """
    mode: str
    tool_dir: Path         # OpenSepia tool root
    project_dir: Path      # Product project root (board/, workspace/, project.yaml)
    agents_config: dict[str, Any]
    project_config: dict[str, Any]
    board_dir: Path
    workspace_dir: Path
    config_dir: Path
    logs_dir: Path

    sprint_num: int = 1
    cycle_num: int = 0
    agent_ids: list[str] = field(default_factory=list)
    agent_results: list[dict[str, Any]] = field(default_factory=list)
    agents_ok: bool = False
    skip_agents: bool = False
    errors: list[OrchestratorError] = field(default_factory=list)

    execution_params: dict[str, Any] = field(default_factory=dict)

    verbose: bool = False
    dry_run: bool = False
    no_increment: bool = False


@runtime_checkable
class Step(Protocol):
    """A single pipeline step."""

    @property
    def name(self) -> str: ...

    @property
    def critical(self) -> bool: ...

    def execute(self, ctx: PipelineContext) -> PipelineContext: ...


class Pipeline:
    """Executes a sequence of Steps, handling errors per step.

    Non-critical steps log errors and continue. Critical steps
    cause the pipeline to abort immediately.
    """

    def __init__(self, steps: list[Step]):
        self.steps = steps

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """Execute all steps in order.

        Args:
            ctx: Pipeline context to flow through steps.

        Returns:
            The context after all steps have run (or the pipeline aborted).

        Raises:
            OrchestratorError: If a critical step fails.
        """
        from opensepia import log
        for step in self.steps:
            try:
                log.step_detail("pipeline", f"Running step: {step.name}")
                ctx = step.execute(ctx)
            except OrchestratorError as e:
                ctx.errors.append(e)
                if step.critical:
                    logger.error("Critical step '%s' failed: %s", step.name, e)
                    raise
                else:
                    logger.warning("Step '%s' failed (non-critical): %s", step.name, e)
            except Exception as e:
                wrapped = OrchestratorError(f"Unexpected error in {step.name}: {e}")
                ctx.errors.append(wrapped)
                if step.critical:
                    logger.error("Critical step '%s' unexpected error: %s", step.name, e)
                    raise OrchestratorError(str(e)) from e
                else:
                    logger.warning("Step '%s' unexpected error (non-critical): %s", step.name, e)

        return ctx
