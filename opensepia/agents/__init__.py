"""
AI Dev Team — Agent execution package.

Modules:
- context: Build agent context from board state, workspace, and inbox
- invoker: Call Claude Code CLI with retry logic
- parser: Parse agent output (---FILES--- format)
- writer: Apply agent output to disk with security checks
- workspace: Directory tree listing for workspace context
"""
