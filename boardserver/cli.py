"""
Board Server — CLI entry point.

Usage:
    boardserver start [--port 8080] [--config board-server.yaml]
    boardserver start --port 8080 --db myboard.db
"""

import argparse
import logging
import sys
from pathlib import Path

from boardserver.config import BoardConfig
from boardserver.db import Database
from boardserver.api import create_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Board Server — Lightweight project board for AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    # start
    start_p = sub.add_parser("start", help="Start the board server")
    start_p.add_argument("--port", "-p", type=int, default=None, help="Port (default: 8080)")
    start_p.add_argument("--host", type=str, default=None, help="Host (default: 0.0.0.0)")
    start_p.add_argument("--config", "-c", type=str, default=None, help="Config file (default: board-server.yaml)")
    start_p.add_argument("--db", type=str, default=None, help="Database file (default: board.db)")
    start_p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        print("\nUsage: boardserver start [--port 8080] [--config board-server.yaml]")
        sys.exit(1)

    if args.command == "start":
        _start(args)


def _start(args: argparse.Namespace) -> None:
    """Start the board server."""
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Load config
    config_path = Path(args.config) if args.config else None
    try:
        config = BoardConfig.load(config_path)
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}")
        sys.exit(1)

    # Override with CLI args
    if args.port:
        config.port = args.port
    if args.host:
        config.host = args.host
    if args.db:
        config.db_path = args.db

    # Open database
    db = Database(config.db_path, config)
    db.connect()

    print(f"Board Server v0.1.0")
    print(f"  Database: {config.db_path}")
    print(f"  Schema:   {len(config.item_types)} item types ({', '.join(config.item_types)})")
    print(f"  Agents:   {len(config.agents)} ({', '.join(config.agents)})")
    print(f"  Events:   {len(config.events)} event types")
    print()
    print(f"  API:  http://{config.host}:{config.port}/api/")
    print(f"  UI:   http://{config.host}:{config.port}/")
    print()

    # Start server
    server = create_server(config, db)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        db.close()
        server.server_close()


if __name__ == "__main__":
    main()
