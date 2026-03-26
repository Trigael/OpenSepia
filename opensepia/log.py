"""
AI Dev Team — Unified output for CLI and pipeline steps.

Two levels:
  info/success/warn/error — always visible
  detail                  — only with --verbose

Usage:
    from opensepia import log
    log.info("Starting cycle")
    log.detail("Loading 9 agents from config")
    log.success("Cycle complete")
    log.warn("Provider not configured")
    log.error("Config file missing")
    log.step("board_health", "Checking board files...")
"""

import sys

_verbose = False


def set_verbose(enabled: bool) -> None:
    """Enable or disable verbose output."""
    global _verbose
    _verbose = enabled


def is_verbose() -> bool:
    return _verbose


def info(msg: str) -> None:
    """Always-visible informational message."""
    print(f"  {msg}")


def detail(msg: str) -> None:
    """Verbose-only detail message."""
    if _verbose:
        print(f"  {msg}")


def success(msg: str) -> None:
    """Always-visible success message."""
    print(f"  {msg}")


def warn(msg: str) -> None:
    """Always-visible warning."""
    print(f"  WARNING: {msg}")


def error(msg: str) -> None:
    """Always-visible error."""
    print(f"  ERROR: {msg}", file=sys.stderr)


def step(name: str, msg: str) -> None:
    """Pipeline step progress — always visible, concise."""
    print(f"  [{name}] {msg}")


def step_detail(name: str, msg: str) -> None:
    """Pipeline step detail — verbose only."""
    if _verbose:
        print(f"  [{name}] {msg}")


def header(title: str) -> None:
    """Section header."""
    print(f"\n  {title}")
    print(f"  {'─' * 50}")


def banner(lines: list[str]) -> None:
    """Multi-line banner."""
    print()
    print("  ============================================")
    for line in lines:
        print(f"  {line}")
    print("  ============================================")
