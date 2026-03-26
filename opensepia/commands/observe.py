"""Observe commands: monitor, history."""

import argparse
import logging
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from opensepia import log
from opensepia.config import OrchestratorConfig
from opensepia.errors import ConfigError

logger = logging.getLogger(__name__)


def cmd_monitor(argv: list[str]) -> None:
    """Show cycle statistics."""
    import json as _json

    parser = argparse.ArgumentParser(prog="opensepia monitor", description="Cycle statistics")
    parser.add_argument("days", nargs="?", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--last", action="store_true", help="Show only last cycle")
    args = parser.parse_args(argv)

    tool_dir = Path(__file__).parent.parent.parent
    try:
        config = OrchestratorConfig.load()
        logs_dir = config.logs_dir
    except ConfigError:
        logs_dir = tool_dir / "project" / "logs" / "runs"

    if args.last:
        latest = logs_dir / "latest.json"
        if not latest.exists():
            print("No logs yet.")
            return
        with open(latest, encoding="utf-8") as f:
            data = _json.load(f)
        print(f"\n  Last cycle: {data.get('timestamp', '?')}")
        for a in data.get("agents", []):
            ctx = a.get("context_chars", 0)
            resp = a.get("response_chars", 0)
            err = f" [ERROR: {a['error']}]" if a.get("error") else ""
            print(f"    {a['agent']}: {ctx} ctx / {resp} resp{err}")
        print()
        return

    # Summary
    from datetime import timedelta as _td
    cutoff = datetime.now() - _td(days=args.days)
    logs = []
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("*.json")):
            if f.name == "latest.json":
                continue
            try:
                ts = datetime.strptime(f.stem, "%Y%m%d_%H%M%S")
                if ts >= cutoff:
                    with open(f, encoding="utf-8") as fh:
                        data = _json.load(fh)
                    data["_ts"] = ts
                    logs.append(data)
            except (ValueError, _json.JSONDecodeError):
                continue

    if not logs:
        print(f"  No logs for the last {args.days} days.")
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

    print(f"\n  Report ({args.days} days)")
    print(f"  {'─' * 40}")
    print(f"  Cycles:  {len(logs)}")
    print(f"  Context: {total_ctx:,} chars")
    print(f"  Output:  {total_resp:,} chars")

    if daily:
        print(f"\n  Daily:")
        for day in sorted(daily):
            d = daily[day]
            print(f"    {day}:  {d['cycles']} cycles, {d['chars']:,} chars")

    if agent_stats:
        print(f"\n  Agents:")
        for name in sorted(agent_stats):
            s = agent_stats[name]
            print(f"    {name:<20} {s['runs']:>3} runs  {s['ctx'] + s['resp']:>10,} chars")
    print()


def cmd_history(argv: list[str]) -> None:
    """Show recent cycle history."""
    import json as _json

    parser = argparse.ArgumentParser(prog="opensepia history", description="Recent cycle history")
    parser.add_argument("count", nargs="?", type=int, default=10, help="Number of cycles (default: 10)")
    args = parser.parse_args(argv)

    try:
        config = OrchestratorConfig.load()
        logs_dir = config.logs_dir
    except ConfigError:
        logs_dir = Path(__file__).parent.parent.parent / "project" / "logs" / "runs"

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

            ts = data.get("timestamp", "?")[:19].replace("T", " ")
            status = data.get("status", "?")
            mode = data.get("mode", "?")
            sprint = data.get("sprint", "?")
            cycle = data.get("cycle", "?")
            ok_count = data.get("agents_ok_count", 0)
            fail_count = data.get("agents_failed_count", 0)

            icon = "+" if status == "ok" else "!"
            agents_str = f"{ok_count} ok" if fail_count == 0 else f"{ok_count} ok, {fail_count} failed"

            log.info(f"[{icon}] S{sprint}C{cycle} {ts} — {mode}, {agents_str}")

            if fail_count > 0:
                failed = data.get("agents_failed", [])
                log.detail(f"    Failed: {', '.join(failed)}")
        except Exception:
            continue

    print()
