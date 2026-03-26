"""
AI Dev Team — Unified output for CLI and pipeline steps.

Two levels:
  info/success/warn/error — always visible
  detail                  — only with --verbose

Color support: auto-detected, disabled on Windows without ANSI support
or when output is piped to a file.
"""

import os
import sys
import platform

_verbose = False
_color = False


def set_verbose(enabled: bool) -> None:
    global _verbose
    _verbose = enabled


def is_verbose() -> bool:
    return _verbose


def _detect_color() -> bool:
    """Auto-detect if the terminal supports color."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if platform.system() == "Windows":
        # Windows 10+ supports ANSI if enabled
        return os.environ.get("TERM") is not None or os.environ.get("WT_SESSION") is not None
    return True


def init(verbose: bool = False) -> None:
    """Initialize log settings. Call once at CLI startup."""
    global _verbose, _color
    _verbose = verbose
    _color = _detect_color()


# --- Color helpers ---

def _c(code: str, text: str) -> str:
    if _color:
        return f"\033[{code}m{text}\033[0m"
    return text


def _green(text: str) -> str: return _c("32", text)
def _yellow(text: str) -> str: return _c("33", text)
def _red(text: str) -> str: return _c("31", text)
def _cyan(text: str) -> str: return _c("36", text)
def _dim(text: str) -> str: return _c("2", text)
def _bold(text: str) -> str: return _c("1", text)


# --- Output functions ---

def info(msg: str) -> None:
    """Always-visible informational message."""
    print(f"  {msg}")


def detail(msg: str) -> None:
    """Verbose-only detail message."""
    if _verbose:
        print(f"  {_dim(msg)}")


def success(msg: str) -> None:
    """Always-visible success message."""
    print(f"  {_green(msg)}")


def warn(msg: str) -> None:
    """Always-visible warning."""
    print(f"  {_yellow('WARNING')}: {msg}")


def error(msg: str) -> None:
    """Always-visible error."""
    print(f"  {_red('ERROR')}: {msg}", file=sys.stderr)


def step(name: str, msg: str) -> None:
    """Pipeline step progress — always visible."""
    print(f"  {_dim(f'[{name}]')} {msg}")


def step_detail(name: str, msg: str) -> None:
    """Pipeline step detail — verbose only."""
    if _verbose:
        print(f"  {_dim(f'[{name}]')} {_dim(msg)}")


def header(title: str) -> None:
    """Section header."""
    print(f"\n  {_bold(title)}")
    print(f"  {'─' * 50}")


def banner(lines: list[str]) -> None:
    """Multi-line banner."""
    sep = "============================================"
    print(f"\n  {_dim(sep)}")
    for line in lines:
        print(f"  {line}")
    print(f"  {_dim(sep)}")


def progress(agent_name: str, index: int, total: int, emoji: str = "") -> None:
    """Agent progress indicator."""
    label = f"{emoji} {agent_name}" if emoji else agent_name
    counter = _dim(f"[{index}/{total}]")
    print(f"  {counter} {label}...")


def agent_done(agent_name: str, files: int, elapsed: float) -> None:
    """Agent completion message."""
    time_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
    print(f"       {_green('done')} — {files} files, {_dim(time_str)}")


def agent_error(agent_name: str, error_msg: str) -> None:
    """Agent failure message."""
    print(f"       {_red('failed')} — {error_msg[:80]}")


def agent_retry(delay: int) -> None:
    """Agent retry message."""
    print(f"       {_yellow('retrying')} in {delay}s...")
