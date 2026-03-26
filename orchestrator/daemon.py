"""
AI Dev Team — Background daemon process.

Double-fork Unix daemon that runs the orchestrator pipeline in a loop.
Controlled via signals: SIGTERM to stop, SIGUSR1 to toggle pause/resume.
State persisted to JSON for CLI introspection.
"""

import os
import sys
import signal
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

from orchestrator.config import OrchestratorConfig
from orchestrator.daemon_state import DaemonState, DAEMON_STATE_FILE
from orchestrator.errors import OrchestratorError, ConfigError, LockError
from orchestrator.lockfile import ProcessLock
from orchestrator.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class OrchestratorDaemon:
    """Background daemon that runs orchestrator cycles in a loop.

    Usage:
        daemon = OrchestratorDaemon(mode="dev-team", pause=60)
        daemon.start()  # forks to background, returns PID to parent
    """

    def __init__(
        self,
        mode: str = "dev-team",
        pause: int = 60,
        verbose: bool = False,
        project_dir: Path | None = None,
    ):
        self.mode = mode
        self.pause = pause
        self.verbose = verbose
        self.project_dir = project_dir or Path(__file__).parent.parent
        self.state_path = self.project_dir / DAEMON_STATE_FILE
        self.log_path = self.project_dir / "logs" / "daemon.log"
        self._stopping = False
        self._paused = False
        self._state = DaemonState(mode=mode, pause_seconds=pause)

    def start(self) -> int:
        """Daemonize and start the run loop. Returns child PID to the parent."""
        # Check not already running
        existing = DaemonState.load(self.state_path)
        if existing.is_process_alive() and existing.status in ("running", "paused"):
            raise RuntimeError(
                f"Daemon already running (PID: {existing.pid}, status: {existing.status})"
            )

        return self._daemonize()

    def _daemonize(self) -> int:
        """Classic double-fork to detach from terminal."""
        # First fork
        pid = os.fork()
        if pid > 0:
            # Parent: wait briefly for grandchild to write state, then return its PID
            time.sleep(0.5)
            state = DaemonState.load(self.state_path)
            return state.pid if state.pid > 0 else pid

        # Child: become session leader
        os.setsid()

        # Second fork
        pid = os.fork()
        if pid > 0:
            os._exit(0)  # First child exits

        # Grandchild: the actual daemon
        os.umask(0o22)
        os.chdir(str(self.project_dir))

        # Redirect stdio
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        sys.stdin.close()
        log_fd = os.open(str(self.log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)  # stdin <- /dev/null
        os.dup2(log_fd, 1)   # stdout -> daemon.log
        os.dup2(log_fd, 2)   # stderr -> daemon.log
        os.close(devnull)
        os.close(log_fd)

        # Setup and run
        self._setup_logging()
        self._install_signal_handlers()

        try:
            self.run_loop()
        except Exception as e:
            logger.exception("Daemon crashed: %s", e)
            self._state.last_cycle_result = "crash"
            self._state.last_cycle_errors = [str(e)]
            self._state.mark_stopped(self.state_path)
        finally:
            os._exit(0)

    def _setup_logging(self) -> None:
        """Configure logging to daemon.log."""
        root = logging.getLogger()
        root.handlers.clear()

        handler = logging.FileHandler(str(self.log_path), encoding="utf-8")
        handler.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.DEBUG if self.verbose else logging.INFO)

    def _install_signal_handlers(self) -> None:
        """Install signal handlers for graceful control."""
        signal.signal(signal.SIGTERM, self._handle_stop)
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGUSR1, self._handle_pause_toggle)

    def _handle_stop(self, signum: int, frame) -> None:
        logger.info("Received signal %d, stopping after current operation...", signum)
        self._stopping = True
        self._update_state(status="stopping")

    def _handle_pause_toggle(self, signum: int, frame) -> None:
        self._paused = not self._paused
        if self._paused:
            logger.info("Daemon paused")
            self._update_state(status="paused", paused_at=datetime.now().isoformat())
        else:
            logger.info("Daemon resumed")
            self._update_state(status="running", paused_at=None)

    def run_loop(self) -> None:
        """Main daemon loop: run cycles with pause between them."""
        daemon_lock = ProcessLock("daemon")
        try:
            daemon_lock.acquire()
        except LockError as e:
            logger.error("Cannot acquire daemon lock: %s", e)
            return

        now = datetime.now()
        self._state = DaemonState(
            pid=os.getpid(),
            status="running",
            mode=self.mode,
            started_at=now.isoformat(),
            pause_seconds=self.pause,
        )
        self._state.save(self.state_path)
        logger.info("Daemon started (PID: %d, mode: %s, pause: %ds)",
                     os.getpid(), self.mode, self.pause)

        try:
            while not self._stopping:
                if self._paused:
                    time.sleep(1)
                    continue

                # Run one cycle
                self._state.current_cycle_started_at = datetime.now().isoformat()
                self._state.current_step = "starting"
                self._state.save(self.state_path)

                result, errors = self._run_single_cycle()

                self._state.cycle_count += 1
                self._state.last_cycle_finished_at = datetime.now().isoformat()
                self._state.last_cycle_result = result
                self._state.last_cycle_errors = errors
                self._state.current_step = None
                self._state.current_cycle_started_at = None

                if not self._stopping:
                    next_time = datetime.now() + timedelta(seconds=self.pause)
                    self._state.next_cycle_at = next_time.isoformat()
                    self._state.save(self.state_path)

                    logger.info(
                        "Cycle %d done (%s). Next at %s",
                        self._state.cycle_count, result,
                        next_time.strftime("%H:%M:%S"),
                    )

                    self._interruptible_sleep(self.pause)
                    self._state.next_cycle_at = None

        except Exception as e:
            logger.exception("Unexpected error in daemon loop: %s", e)
        finally:
            daemon_lock.release()
            self._state.mark_stopped(self.state_path)
            logger.info("Daemon stopped")

    def _run_single_cycle(self) -> tuple[str, list[str]]:
        """Execute one pipeline cycle, tracking steps in state."""
        from orchestrator.cli import build_pipeline

        try:
            config = OrchestratorConfig.load(self.project_dir)
            agent_ids = config.resolve_agent_ids(self.mode)
        except ConfigError as e:
            logger.error("Config error: %s", e)
            return "error", [str(e)]

        # Acquire per-mode lock for this cycle
        mode_lock = ProcessLock(self.mode)
        try:
            mode_lock.acquire()
        except LockError as e:
            logger.warning("Mode lock busy: %s", e)
            return "skipped", [str(e)]

        try:
            ctx = PipelineContext(
                mode=self.mode,
                project_dir=config.project_dir,
                agents_config=config.agents,
                project_config=config.project,
                board_dir=config.board_dir,
                workspace_dir=config.workspace_dir,
                config_dir=config.config_dir,
                logs_dir=config.logs_dir,
                sprint_num=config.sprint_num,
                cycle_num=config.cycle_num,
                agent_ids=agent_ids,
                verbose=self.verbose,
            )

            pipeline = build_pipeline()

            # Run steps individually to track current_step in state
            for step in pipeline.steps:
                if self._stopping:
                    break
                self._update_state(current_step=step.name)
                try:
                    ctx = step.execute(ctx)
                except OrchestratorError as e:
                    ctx.errors.append(e)
                    if step.critical:
                        logger.error("Critical step '%s' failed: %s", step.name, e)
                        break
                    else:
                        logger.warning("Step '%s' failed: %s", step.name, e)
                except Exception as e:
                    wrapped = OrchestratorError(f"Unexpected error in {step.name}: {e}")
                    ctx.errors.append(wrapped)
                    if step.critical:
                        logger.error("Critical step '%s' crashed: %s", step.name, e)
                        break
                    else:
                        logger.warning("Step '%s' crashed: %s", step.name, e)

            errors = [str(e) for e in ctx.errors]
            return ("error" if errors else "ok"), errors

        except Exception as e:
            logger.exception("Cycle failed: %s", e)
            return "error", [str(e)]
        finally:
            mode_lock.release()

    def _update_state(self, **kwargs) -> None:
        """Update specific fields and save."""
        for k, v in kwargs.items():
            setattr(self._state, k, v)
        self._state.save(self.state_path)

    def _interruptible_sleep(self, seconds: int) -> None:
        """Sleep in 1-second increments, checking stop/pause flags."""
        for _ in range(seconds):
            if self._stopping:
                return
            if self._paused:
                self._update_state(status="paused", next_cycle_at=None)
                while self._paused and not self._stopping:
                    time.sleep(1)
                if not self._stopping:
                    self._update_state(status="running")
                return
            time.sleep(1)


def stop_daemon(project_dir: Path | None = None) -> bool:
    """Send SIGTERM to running daemon. Returns True if stopped."""
    project_dir = project_dir or Path(__file__).parent.parent
    state_path = project_dir / DAEMON_STATE_FILE
    state = DaemonState.load(state_path)

    if not state.is_process_alive():
        if state.status != "stopped":
            state.mark_stopped(state_path)
        return False

    os.kill(state.pid, signal.SIGTERM)

    # Wait for graceful shutdown
    for _ in range(60):  # 30 seconds (0.5s intervals)
        time.sleep(0.5)
        if not state.is_process_alive():
            return True

    # Force kill
    try:
        os.kill(state.pid, signal.SIGKILL)
        time.sleep(0.5)
    except ProcessLookupError:
        pass

    state.mark_stopped(state_path)
    return True


def send_pause_signal(project_dir: Path | None = None) -> str:
    """Send SIGUSR1 to toggle pause/resume. Returns new status."""
    project_dir = project_dir or Path(__file__).parent.parent
    state_path = project_dir / DAEMON_STATE_FILE
    state = DaemonState.load(state_path)

    if not state.is_process_alive():
        raise RuntimeError("Daemon is not running")

    os.kill(state.pid, signal.SIGUSR1)

    # Wait for state to update
    time.sleep(1)
    new_state = DaemonState.load(state_path)
    return new_state.status


def get_daemon_status(project_dir: Path | None = None) -> DaemonState:
    """Load and validate daemon state. Cleans up stale state."""
    project_dir = project_dir or Path(__file__).parent.parent
    state_path = project_dir / DAEMON_STATE_FILE
    state = DaemonState.load(state_path)

    # Clean up stale state
    if state.status in ("running", "paused", "stopping") and not state.is_process_alive():
        state.status = "crashed"
        state.save(state_path)

    return state
