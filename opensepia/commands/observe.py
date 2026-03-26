"""Observe commands: monitor, history, logs."""

import argparse
import logging
import time
import collections
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from opensepia import log
from opensepia.config import OrchestratorConfig
from opensepia.errors import ConfigError

logger = logging.getLogger(__name__)


def _get_project_dirs() -> tuple[Path, Path]:
    """Get tool_dir and logs_dir, with fallbacks."""
    try:
        config = OrchestratorConfig.load()
        return config.tool_dir, config.logs_dir
    except ConfigError:
        tool_dir = Path(__file__).parent.parent.parent
        return tool_dir, tool_dir / "project" / "logs" / "runs"


def cmd_logs(argv: list[str]) -> None:
    """View logs — daemon log, cycle output, or standup."""
    parser = argparse.ArgumentParser(prog="opensepia logs", description="View logs")
    parser.add_argument("--lines", "-n", type=int, default=50, help="Number of lines (default: 50)")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow log output")
    parser.add_argument("--standup", "-s", action="store_true", help="Show current standup")
    parser.add_argument("--cycle", "-c", action="store_true", help="Show last cycle detail")
    args = parser.parse_args(argv)

    tool_dir, logs_dir = _get_project_dirs()

    if args.standup:
        _show_standup(tool_dir)
        return

    if args.cycle:
        _show_last_cycle(logs_dir)
        return

    # Default: show daemon log, or tell user what's available
    daemon_log = tool_dir / "logs" / "daemon.log"
    if daemon_log.exists():
        if args.follow:
            _tail_follow(daemon_log, args.lines)
        else:
            _tail_lines(daemon_log, args.lines)
    else:
        # No daemon log — show what's available instead
        log.info("No daemon log (daemon hasn't run yet).")
        log.info("")
        log.info("Available views:")
        log.info("  opensepia logs --standup    Show standup from last cycle")
        log.info("  opensepia logs --cycle      Show last cycle details")
        log.info("  opensepia history           Show cycle history")
        log.info("  opensepia board             Show sprint board")


def _show_standup(tool_dir: Path) -> None:
    """Show the current standup file."""
    try:
        config = OrchestratorConfig.load()
        standup_path = config.board_dir / "standup.md"
    except ConfigError:
        standup_path = tool_dir / "project" / "board" / "standup.md"

    if not standup_path.exists():
        log.info("No standup yet.")
        return

    content = standup_path.read_text(encoding="utf-8")

    # Find the agent reports — they come after the header and any <details> blocks
    # Strip HTML tags for display
    clean = content
    # Remove <details>...</details> blocks
    import re
    clean = re.sub(r'<details>.*?</details>', '', clean, flags=re.DOTALL)
    clean = clean.strip()

    if not clean or clean == f"# Standup — Sprint" or len(clean) < 30:
        # Current cycle has no reports yet — show the previous cycle's standup
        # which is inside the <details> block
        details_match = re.search(r'<details>.*?<summary>.*?</summary>(.*?)</details>', content, re.DOTALL)
        if details_match:
            clean = details_match.group(1).strip()
            log.info("(Showing previous cycle's standup)")
            print()

    if not clean.strip():
        log.info("Standup is empty.")
        return

    log.header("Standup")
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            log.info(stripped)
        elif stripped.startswith("## "):
            print()
            log.info(stripped)
        elif stripped.startswith("- **"):
            log.info(f"  {stripped}")
        elif stripped:
            log.detail(f"  {stripped}")
    print()


def _show_last_cycle(logs_dir: Path) -> None:
    """Show detailed info about the last cycle."""
    import json

    if not logs_dir.exists():
        log.info("No cycle logs yet.")
        return

    # Find the latest cycle log
    log_files = sorted(logs_dir.glob("cycle_*.json"), reverse=True)
    if not log_files:
        # Try the agent run logs
        log_files = sorted(logs_dir.glob("*.json"), reverse=True)
        log_files = [f for f in log_files if f.name != "latest.json"]

    if not log_files:
        log.info("No cycle logs yet.")
        return

    with open(log_files[0], encoding="utf-8") as f:
        data = json.load(f)

    ts = data.get("timestamp", "?")
    if isinstance(ts, str) and "T" in ts:
        ts = ts[:19].replace("T", " ")

    log.header("Last Cycle")
    log.info(f"Time:   {ts}")
    log.info(f"Mode:   {data.get('mode', '?')}")
    log.info(f"Sprint: {data.get('sprint', '?')}  Cycle: {data.get('cycle', '?')}")
    log.info(f"Status: {data.get('status', '?')}")

    ok = data.get("agents_ok", [])
    failed = data.get("agents_failed", [])
    log.info(f"Agents: {len(ok)} ok, {len(failed)} failed")

    agents = data.get("agents", [])
    if agents:
        print()
        log.info("Per agent:")
        for a in agents:
            name = a.get("agent", "?")
            ctx = a.get("context_chars", 0)
            resp = a.get("response_chars", 0)
            err = a.get("error")
            if err:
                log.info(f"  {name:<20} FAILED: {err[:60]}")
            else:
                log.info(f"  {name:<20} {ctx:>6,} ctx / {resp:>6,} resp")

    if failed:
        print()
        log.warn(f"Failed agents: {', '.join(failed)}")

    print()


def _tail_lines(path: Path, n: int) -> None:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = collections.deque(f, maxlen=n)
    for line in lines:
        print(line, end="")


def _tail_follow(path: Path, n: int) -> None:
    _tail_lines(path, n)
    print("--- following (Ctrl+C to stop) ---")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n--- stopped ---")


def cmd_monitor(argv: list[str]) -> None:
    """Show cycle statistics."""
    import json as _json

    parser = argparse.ArgumentParser(prog="opensepia monitor", description="Cycle statistics")
    parser.add_argument("days", nargs="?", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--last", action="store_true", help="Show only last cycle")
    args = parser.parse_args(argv)

    _, logs_dir = _get_project_dirs()

    if args.last:
        _show_last_cycle(logs_dir)
        return

    cutoff = datetime.now() - timedelta(days=args.days)
    logs = []
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("*.json")):
            if f.name == "latest.json":
                continue
            try:
                ts = datetime.strptime(f.stem.replace("cycle_", ""), "%Y%m%d_%H%M%S")
                if ts >= cutoff:
                    with open(f, encoding="utf-8") as fh:
                        data = _json.load(fh)
                    data["_ts"] = ts
                    logs.append(data)
            except (ValueError, _json.JSONDecodeError):
                continue

    if not logs:
        log.info(f"No logs for the last {args.days} days.")
        return

    total_ctx = sum(sum(a.get("context_chars", 0) for a in l.get("agents", [])) for l in logs)
    total_resp = sum(sum(a.get("response_chars", 0) for a in l.get("agents", [])) for l in logs)

    daily = defaultdict(lambda: {"cycles": 0, "chars": 0})
    for l in logs:
        day = l["_ts"].strftime("%Y-%m-%d")
        daily[day]["cycles"] += 1
        daily[day]["chars"] += sum(a.get("context_chars", 0) + a.get("response_chars", 0) for a in l.get("agents", []))

    agent_stats = defaultdict(lambda: {"runs": 0, "ctx": 0, "resp": 0})
    for l in logs:
        for a in l.get("agents", []):
            n = a["agent"]
            agent_stats[n]["runs"] += 1
            agent_stats[n]["ctx"] += a.get("context_chars", 0)
            agent_stats[n]["resp"] += a.get("response_chars", 0)

    log.header(f"Report ({args.days} days)")
    log.info(f"Cycles:  {len(logs)}")
    log.info(f"Context: {total_ctx:,} chars")
    log.info(f"Output:  {total_resp:,} chars")

    if daily:
        log.info("")
        log.info("Daily:")
        for day in sorted(daily):
            d = daily[day]
            log.info(f"  {day}:  {d['cycles']} cycles, {d['chars']:,} chars")

    if agent_stats:
        log.info("")
        log.info("Agents:")
        for name in sorted(agent_stats):
            s = agent_stats[name]
            log.detail(f"  {name:<20} {s['runs']:>3} runs  {s['ctx'] + s['resp']:>10,} chars")
    log.info("")


def cmd_history(argv: list[str]) -> None:
    """Show recent cycle history with per-agent detail."""
    import json as _json

    parser = argparse.ArgumentParser(prog="opensepia history", description="Recent cycle history")
    parser.add_argument("count", nargs="?", type=int, default=10, help="Number of cycles (default: 10)")
    parser.add_argument("--detail", "-d", action="store_true", help="Show per-agent detail")
    args = parser.parse_args(argv)

    _, logs_dir = _get_project_dirs()

    if not logs_dir.exists():
        log.info("No cycle history yet.")
        return

    log_files = sorted(logs_dir.glob("cycle_*.json"), reverse=True)[:args.count]

    if not log_files:
        log.info("No cycle history yet.")
        return

    log.header("Cycle History")
    for f in reversed(log_files):
        try:
            with open(f, encoding="utf-8") as fh:
                data = _json.load(fh)

            ts = data.get("timestamp", "?")
            if isinstance(ts, str) and "T" in ts:
                ts = ts[:19].replace("T", " ")

            status = data.get("status", "?")
            mode = data.get("mode", "?")
            sprint = data.get("sprint", "?")
            cycle = data.get("cycle", "?")
            ok_count = data.get("agents_ok_count", 0)
            fail_count = data.get("agents_failed_count", 0)

            icon = "+" if status == "ok" else "!"
            agents_str = f"{ok_count} ok" if fail_count == 0 else f"{ok_count} ok, {fail_count} failed"

            log.info(f"[{icon}] S{sprint}C{cycle} {ts} — {mode}, {agents_str}")

            if args.detail:
                agents = data.get("agents", [])
                for a in agents:
                    name = a.get("agent", "?")
                    ctx = a.get("context_chars", 0)
                    resp = a.get("response_chars", 0)
                    err = a.get("error")
                    if err:
                        log.detail(f"      {name}: FAILED — {err[:50]}")
                    else:
                        log.detail(f"      {name}: {ctx:,} ctx / {resp:,} resp")

            if fail_count > 0 and not args.detail:
                failed = data.get("agents_failed", [])
                log.detail(f"    Failed: {', '.join(failed)}")
        except Exception:
            continue

    log.info("")
