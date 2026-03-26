"""
AI Dev Team — Daemon worker process (Windows entry point).

On Windows, the daemon is launched as a detached subprocess running this module.
On Unix, the daemon uses fork() directly and this module is not used.
"""

import argparse
import logging
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="dev-team")
    parser.add_argument("--pause", type=int, default=60)
    parser.add_argument("--tool-dir", required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    tool_dir = Path(args.tool_dir)
    sys.path.insert(0, str(tool_dir))

    from opensepia.daemon import OrchestratorDaemon

    daemon = OrchestratorDaemon(
        mode=args.mode,
        pause=args.pause,
        verbose=args.verbose,
        tool_dir=tool_dir,
    )
    daemon._setup_logging()
    daemon.run_loop()


if __name__ == "__main__":
    main()
