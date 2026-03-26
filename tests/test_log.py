"""Tests for opensepia/log.py — unified output module."""

import io
import sys
import pytest

from opensepia import log


@pytest.fixture(autouse=True)
def reset_log_state():
    """Reset log state before each test."""
    log.init(verbose=False)
    yield
    log.init(verbose=False)


def _capture(func, *args):
    """Capture stdout from a log function call."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    func(*args)
    sys.stdout = old
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Verbose control
# ---------------------------------------------------------------------------

def test_init_sets_verbose():
    log.init(verbose=True)
    assert log.is_verbose() is True
    log.init(verbose=False)
    assert log.is_verbose() is False


def test_detail_hidden_when_not_verbose():
    log.init(verbose=False)
    output = _capture(log.detail, "secret detail")
    assert output == ""


def test_detail_shown_when_verbose():
    log.init(verbose=True)
    output = _capture(log.detail, "visible detail")
    assert "visible detail" in output


def test_step_detail_hidden_when_not_verbose():
    log.init(verbose=False)
    output = _capture(log.step_detail, "step", "hidden")
    assert output == ""


def test_step_detail_shown_when_verbose():
    log.init(verbose=True)
    output = _capture(log.step_detail, "step", "visible")
    assert "visible" in output


# ---------------------------------------------------------------------------
# Always-visible output
# ---------------------------------------------------------------------------

def test_info_always_visible():
    output = _capture(log.info, "hello")
    assert "hello" in output


def test_success_always_visible():
    output = _capture(log.success, "done")
    assert "done" in output


def test_step_always_visible():
    output = _capture(log.step, "git_sync", "pushing")
    assert "pushing" in output
    assert "git_sync" in output


def test_warn_always_visible():
    output = _capture(log.warn, "careful")
    assert "careful" in output
    assert "WARNING" in output


def test_progress_shows_counter():
    output = _capture(log.progress, "Dev 1", 2, 6, "🟢")
    assert "Dev 1" in output
    assert "2/6" in output


def test_agent_done_shows_files_and_time():
    output = _capture(log.agent_done, "Dev 1", 5, 42.3)
    assert "done" in output
    assert "5 files" in output
    assert "42s" in output


def test_agent_error_shows_message():
    output = _capture(log.agent_error, "Dev 1", "timeout after 900s")
    assert "failed" in output
    assert "timeout" in output


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def test_header():
    output = _capture(log.header, "My Section")
    assert "My Section" in output
    assert "─" in output


def test_banner():
    output = _capture(log.banner, ["Line 1", "Line 2"])
    assert "Line 1" in output
    assert "Line 2" in output
    assert "====" in output
