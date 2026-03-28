"""
AI Dev Team — Background daemon process.

Cross-platform daemon that runs the orchestrator pipeline in a loop.
- Unix: double-fork daemonization
- Windows: subprocess.Popen with detached process

Control is file-based for cross-platform compatibility:
- Stop: write "stop" to logs/daemon_control
- Pause/Resume: write "pause"/"resume" to logs/daemon_control

State persisted to JSON for CLI introspection.
"""

import os
import sys
import signal
import subprocess
import time
import logging
import platform
from datetime import datetime, timedelta
from pathlib import Path

from opensepia.config import OrchestratorConfig
from opensepia.daemon_state import DaemonState, DAEMON_STATE_FILE
from opensepia.errors import OrchestratorError, ConfigError, LockError
from opensepia.lockfile import ProcessLock
from opensepia.pipeline import PipelineContext

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"
CONTROL_FILE = "logs/daemon_control"


class OrchestratorDaemon:
    """Background daemon that runs orchestrator cycles in a loop.

    Cross-platform: uses fork on Unix, subprocess on Windows.
    Control via file-based signals (logs/daemon_control).
    """

    def __init__(
        self,
        mode: str = "dev-team",
        pause: int = 60,
        verbose: bool = False,
        tool_dir: Path | None = None,
        max_cycles: int = 0,
        max_sprints: int = 0,
    ):
        self.mode = mode
        self.pause = pause
        self.verbose = verbose
        self.max_cycles = max_cycles    # 0 = unlimited
        self.max_sprints = max_sprints  # 0 = unlimited
        self.tool_dir = tool_dir or Path(__file__).parent.parent
        self.state_path = self.tool_dir / DAEMON_STATE_FILE
        self.log_path = self.tool_dir / "logs" / "daemon.log"
        self.control_path = self.tool_dir / CONTROL_FILE
        self._stopping = False
        self._paused = False
        self._state = DaemonState(mode=mode, pause_seconds=pause)

    def start(self) -> int:
        """Detach and start the run loop. Returns child PID to the parent."""
        existing = DaemonState.load(self.state_path)
        if existing.is_process_alive() and existing.status in ("running", "paused"):
            raise RuntimeError(
                f"Daemon already running (PID: {existing.pid}, status: {existing.status})"
            )

        # Clear any stale control file
        self.control_path.unlink(missing_ok=True)

        if IS_WINDOWS:
            return self._start_windows()
        else:
            return self._start_unix()

    def _start_unix(self) -> int:
        """Unix: classic double-fork to detach from terminal."""
        pid = os.fork()
        if pid > 0:
            time.sleep(0.5)
            state = DaemonState.load(self.state_path)
            return state.pid if state.pid > 0 else pid

        os.setsid()

        pid = os.fork()
        if pid > 0:
            os._exit(0)

        os.umask(0o22)
        os.chdir(str(self.tool_dir))

        # Redirect stdio
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        sys.stdin.close()
        log_fd = os.open(str(self.log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        os.close(devnull)
        os.close(log_fd)

        self._setup_logging()
        self._install_signal_handlers()

        try:
            self.run_loop()
        except (OSError, RuntimeError, OrchestratorError) as e:
            logger.exception("Daemon crashed: %s", e)
            self._state.last_cycle_result = "crash"
            self._state.last_cycle_errors = [str(e)]
            self._state.mark_stopped(self.state_path)
        finally:
            os._exit(0)

    def _start_windows(self) -> int:
        """Windows: launch a detached subprocess."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Launch python -m opensepia._daemon_worker as a detached process
        cmd = [
            sys.executable, "-m", "opensepia._daemon_worker",
            "--mode", self.mode,
            "--pause", str(self.pause),
            "--cycles", str(self.max_cycles),
            "--sprints", str(self.max_sprints),
            "--tool-dir", str(self.tool_dir),
        ]
        if self.verbose:
            cmd.append("--verbose")

        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008

        with open(self.log_path, "a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                cwd=str(self.tool_dir),
            )

        # Wait for worker to write state
        time.sleep(1)
        state = DaemonState.load(self.state_path)
        return state.pid if state.pid > 0 else proc.pid

    def _setup_logging(self) -> None:
        """Configure logging to daemon.log.

        Uses structured JSON format when the OPENSEPIA_LOG_FORMAT env var
        is set to "json"; otherwise falls back to the default human-readable
        format.
        """
        from opensepia.log import wants_json_logging, setup_json_logging

        level = logging.DEBUG if self.verbose else logging.INFO

        if wants_json_logging():
            setup_json_logging(str(self.log_path), level=level)
            return

        root = logging.getLogger()
        root.handlers.clear()

        handler = logging.FileHandler(str(self.log_path), encoding="utf-8")
        handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(level)

    def _install_signal_handlers(self) -> None:
        """Install signal handlers (Unix only, safe no-op on Windows)."""
        if not IS_WINDOWS:
            signal.signal(signal.SIGTERM, self._handle_stop)
            signal.signal(signal.SIGINT, self._handle_stop)

    def _handle_stop(self, signum: int, frame) -> None:
        # Only set flag — no file I/O in signal handler (not async-safe).
        # The main loop will persist the "stopping" status on its next iteration.
        self._stopping = True

    def _check_control_file(self) -> None:
        """Check for file-based control commands (cross-platform)."""
        if not self.control_path.exists():
            return
        try:
            cmd = self.control_path.read_text(encoding="utf-8").strip().lower()
            self.control_path.unlink(missing_ok=True)

            if cmd == "stop":
                logger.info("Received stop command via control file")
                self._stopping = True
                self._update_state(status="stopping")
            elif cmd == "pause":
                if not self._paused:
                    self._paused = True
                    logger.info("Daemon paused via control file")
                    self._update_state(status="paused", paused_at=datetime.now().isoformat())
            elif cmd == "resume":
                if self._paused:
                    self._paused = False
                    logger.info("Daemon resumed via control file")
                    self._update_state(status="running", paused_at=None)
        except OSError as e:
            logger.debug("Control file read error: %s", e)

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
        limits = ""
        if self.max_cycles:
            limits += f", max {self.max_cycles} cycles"
        if self.max_sprints:
            limits += f", max {self.max_sprints} sprints"
        logger.info("Daemon started (PID: %d, mode: %s, pause: %ds%s)",
                     os.getpid(), self.mode, self.pause, limits)

        starting_sprint = None

        try:
            while not self._stopping:
                self._check_control_file()
                if self._stopping:
                    break
                if self._paused:
                    time.sleep(1)
                    continue

                self._state.current_cycle_started_at = datetime.now().isoformat()
                self._state.current_step = "starting"
                self._state.save(self.state_path)

                cycle_start = datetime.now()
                logger.info("=== Cycle %d starting (mode: %s) ===",
                            self._state.cycle_count + 1, self.mode)

                result, errors = self._run_single_cycle()

                cycle_elapsed = (datetime.now() - cycle_start).total_seconds()
                logger.info("=== Cycle %d done (%s, %.0fs) — %s ===",
                            self._state.cycle_count + 1, result, cycle_elapsed,
                            f"{len(errors)} errors" if errors else "clean")

                self._state.cycle_count += 1
                self._state.last_cycle_finished_at = datetime.now().isoformat()
                self._state.last_cycle_result = result
                self._state.last_cycle_errors = errors
                self._state.current_step = None
                self._state.current_cycle_started_at = None

                # Reap orphaned agent child processes from this cycle
                try:
                    from opensepia.agents.reaper import reap_orphaned_agents
                    reaped = reap_orphaned_agents()
                    if reaped:
                        logger.info("Reaped %d orphaned agent processes", reaped)
                except Exception:
                    logger.debug("Process reaping failed", exc_info=True)

                # Check cycle limit
                if self.max_cycles and self._state.cycle_count >= self.max_cycles:
                    logger.info("Reached max cycles (%d). Stopping.", self.max_cycles)
                    break

                # Check sprint limit
                if self.max_sprints:
                    try:
                        from opensepia.config import OrchestratorConfig
                        config = OrchestratorConfig.load(self.tool_dir)
                        current_sprint = config.sprint_num
                        if starting_sprint is None:
                            starting_sprint = current_sprint
                        sprints_done = current_sprint - starting_sprint
                        if sprints_done >= self.max_sprints:
                            logger.info("Reached max sprints (%d). Stopping.", self.max_sprints)
                            break
                    except (ConfigError, OSError, ValueError) as e:
                        logger.debug("Sprint limit check failed: %s", e)

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

        except (OSError, RuntimeError, OrchestratorError) as e:
            logger.exception("Unexpected error in daemon loop: %s", e)
        finally:
            # Final reap before exiting
            try:
                from opensepia.agents.reaper import reap_orphaned_agents
                reap_orphaned_agents()
            except Exception:
                pass
            daemon_lock.release()
            self._state.mark_stopped(self.state_path)
            logger.info("Daemon stopped")

    def _run_single_cycle(self) -> tuple[str, list[str]]:
        """Execute one pipeline cycle, tracking steps in state."""
        from opensepia.cli import build_pipeline

        try:
            config = OrchestratorConfig.load(self.tool_dir)
            agent_ids = config.resolve_agent_ids(self.mode)
        except ConfigError as e:
            logger.error("Config error: %s", e)
            return "error", [str(e)]

        mode_lock = ProcessLock(self.mode)
        try:
            mode_lock.acquire()
        except LockError as e:
            logger.warning("Mode lock busy: %s", e)
            return "skipped", [str(e)]

        try:
            from opensepia.board_adapter import create_board_adapter
            board_adapter = create_board_adapter(
                config.board_dir, config.workspace_dir, config.project_dir,
            )

            ctx = PipelineContext(
                mode=self.mode,
                tool_dir=config.tool_dir,
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
                execution_params=config.get_execution_params(),
                verbose=self.verbose,
                board_adapter=board_adapter,
            )

            # Check for interrupted cycle
            from opensepia.cycle_state import CycleState, CYCLE_STATE_FILE
            cs_path = config.project_dir / CYCLE_STATE_FILE
            loaded_state = CycleState.load(cs_path)
            resume_state: CycleState | None = loaded_state if loaded_state.is_interrupted else None

            pipeline = build_pipeline(config.agents, agent_ids=agent_ids)
            ctx = pipeline.run(ctx, resume_state=resume_state)

            errors = [str(e) for e in ctx.errors]
            return ("error" if errors else "ok"), errors

        except (OSError, RuntimeError, OrchestratorError, ValueError) as e:
            logger.exception("Cycle failed: %s", e)
            return "error", [str(e)]
        finally:
            mode_lock.release()

    def _update_state(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self._state, k, v)
        self._state.save(self.state_path)

    def _interruptible_sleep(self, seconds: int) -> None:
        """Sleep in 1-second increments, checking stop/pause via control file."""
        for _ in range(seconds):
            if self._stopping:
                return
            self._check_control_file()
            if self._stopping:
                return
            if self._paused:
                self._update_state(status="paused", next_cycle_at=None)
                while self._paused and not self._stopping:
                    time.sleep(1)
                    self._check_control_file()
                if not self._stopping:
                    self._update_state(status="running")
                return
            time.sleep(1)


# =============================================================================
# CLI helper functions
# =============================================================================

def _write_control(tool_dir: Path, command: str) -> None:
    """Write a command to the daemon control file."""
    control_path = tool_dir / CONTROL_FILE
    control_path.parent.mkdir(parents=True, exist_ok=True)
    control_path.write_text(command, encoding="utf-8")


def _terminate_process(pid: int) -> None:
    """Terminate a process by PID (cross-platform)."""
    if IS_WINDOWS:
        # Windows: use taskkill
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
        )
    else:
        os.kill(pid, signal.SIGKILL)


def stop_daemon(tool_dir: Path | None = None) -> bool:
    """Stop the running daemon. Returns True if stopped."""
    tool_dir = tool_dir or Path(__file__).parent.parent
    state_path = tool_dir / DAEMON_STATE_FILE
    state = DaemonState.load(state_path)

    if not state.is_process_alive():
        if state.status != "stopped":
            state.mark_stopped(state_path)
        return False

    # Send stop command via control file
    _write_control(tool_dir, "stop")

    # Also send SIGTERM on Unix for immediate signal handling
    if not IS_WINDOWS:
        try:
            os.kill(state.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    # Wait for graceful shutdown
    for _ in range(60):
        time.sleep(0.5)
        if not state.is_process_alive():
            return True

    # Force kill
    try:
        _terminate_process(state.pid)
        time.sleep(0.5)
    except (ProcessLookupError, PermissionError):
        pass

    state.mark_stopped(state_path)
    return True


def send_pause_command(tool_dir: Path | None = None, pause: bool = True) -> str:
    """Send pause or resume command. Returns new status."""
    tool_dir = tool_dir or Path(__file__).parent.parent
    state_path = tool_dir / DAEMON_STATE_FILE
    state = DaemonState.load(state_path)

    if not state.is_process_alive():
        raise RuntimeError("Daemon is not running")

    _write_control(tool_dir, "pause" if pause else "resume")

    # Wait for state to update
    time.sleep(2)
    new_state = DaemonState.load(state_path)
    return new_state.status


def get_daemon_status(tool_dir: Path | None = None) -> DaemonState:
    """Load and validate daemon state. Cleans up stale state."""
    tool_dir = tool_dir or Path(__file__).parent.parent
    state_path = tool_dir / DAEMON_STATE_FILE
    state = DaemonState.load(state_path)

    if state.status in ("running", "paused", "stopping") and not state.is_process_alive():
        state.status = "crashed"
        state.save(state_path)

    return state
