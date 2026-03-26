"""
AI Dev Team — Pipeline runner with cycle checkpointing.

Defines the Step protocol and Pipeline class that executes steps
sequentially with structured error handling and resumability.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from opensepia.errors import OrchestratorError
from opensepia.cycle_state import CycleState, CYCLE_STATE_FILE
from opensepia.board_adapter import BoardAdapter

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Shared mutable state flowing through the pipeline."""
    mode: str
    tool_dir: Path
    project_dir: Path
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

    # Board adapter (set by caller — required for agent execution)
    board_adapter: BoardAdapter | None = None  # None only in tests that don't run agents

    # Cycle state for checkpointing (set by Pipeline.run)
    cycle_state: CycleState | None = None


@runtime_checkable
class Step(Protocol):
    """A single pipeline step."""

    @property
    def name(self) -> str: ...

    @property
    def critical(self) -> bool: ...

    def execute(self, ctx: PipelineContext) -> PipelineContext: ...


class Pipeline:
    """Executes steps with checkpointing for resumability.

    After each step completes, the cycle state is saved. On resume,
    completed steps are skipped.
    """

    def __init__(self, steps: list[Step]):
        self.steps = steps

    def run(self, ctx: PipelineContext, resume_state: CycleState | None = None) -> PipelineContext:
        """Execute steps in order, checkpointing after each.

        Args:
            ctx: Pipeline context.
            resume_state: If provided, resume from this interrupted state
                          (skip already-completed steps).

        Returns:
            The context after all steps have run.
        """
        from opensepia import log

        state_path = ctx.project_dir / CYCLE_STATE_FILE

        # Initialize or resume cycle state
        if resume_state and resume_state.is_interrupted:
            state = resume_state
            state.status = "in_progress"
            completed = set(state.completed_steps)
            log.info(f"Resuming interrupted cycle {state.cycle_id}")
            log.detail(f"Completed steps: {', '.join(state.completed_steps)}")
        else:
            state = CycleState(
                cycle_id=f"s{ctx.sprint_num}c{ctx.cycle_num}",
                sprint=ctx.sprint_num,
                cycle=ctx.cycle_num,
                mode=ctx.mode,
                status="in_progress",
                agent_ids=list(ctx.agent_ids),
                started_at=datetime.now().isoformat(),
            )
            completed = set()

        state.save(state_path)
        ctx.cycle_state = state

        for step in self.steps:
            # Skip already-completed steps on resume
            if step.name in completed:
                log.step_detail("pipeline", f"Skipping {step.name} (already done)")
                continue

            try:
                log.step_detail("pipeline", f"Running step: {step.name}")
                state.current_step = step.name
                state.save(state_path)

                ctx = step.execute(ctx)

                state.mark_step_complete(step.name, state_path)

            except OrchestratorError as e:
                ctx.errors.append(e)
                if step.critical:
                    logger.error("Critical step '%s' failed: %s", step.name, e)
                    state.mark_failed(state_path)
                    raise
                else:
                    logger.warning("Step '%s' failed (non-critical): %s", step.name, e)
                    state.mark_step_complete(step.name, state_path)

            except Exception as e:
                wrapped = OrchestratorError(f"Unexpected error in {step.name}: {e}")
                ctx.errors.append(wrapped)
                if step.critical:
                    logger.error("Critical step '%s' unexpected error: %s", step.name, e)
                    state.mark_failed(state_path)
                    raise OrchestratorError(str(e)) from e
                else:
                    logger.warning("Step '%s' unexpected error (non-critical): %s", step.name, e)
                    state.mark_step_complete(step.name, state_path)

        state.mark_completed(state_path)
        return ctx
