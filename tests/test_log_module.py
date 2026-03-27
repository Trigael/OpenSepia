"""Tests for opensepia/log.py — CLI output and JSON logging."""

import json
import logging
import os
from io import StringIO
from unittest.mock import patch

import pytest

from opensepia import log


# =============================================================================
# Verbose / init
# =============================================================================

class TestVerboseAndInit:
    def test_set_verbose(self):
        log.set_verbose(True)
        assert log.is_verbose() is True
        log.set_verbose(False)
        assert log.is_verbose() is False

    def test_init_sets_verbose(self):
        log.init(verbose=True)
        assert log.is_verbose() is True
        log.init(verbose=False)
        assert log.is_verbose() is False


# =============================================================================
# Color detection
# =============================================================================

class TestColorDetection:
    @patch.dict(os.environ, {"NO_COLOR": "1"})
    def test_no_color_env(self):
        assert log._detect_color() is False

    def test_non_tty_no_color(self):
        with patch("sys.stdout", new=StringIO()):
            assert log._detect_color() is False


# =============================================================================
# Color helpers
# =============================================================================

class TestColorHelpers:
    def test_c_with_color_enabled(self):
        log._color = True
        assert "\033[32m" in log._green("hi")
        assert "\033[33m" in log._yellow("hi")
        assert "\033[31m" in log._red("hi")
        assert "\033[36m" in log._cyan("hi")
        assert "\033[2m" in log._dim("hi")
        assert "\033[1m" in log._bold("hi")

    def test_c_without_color(self):
        log._color = False
        assert log._green("hi") == "hi"
        assert log._yellow("hi") == "hi"
        assert log._red("hi") == "hi"
        assert log._cyan("hi") == "hi"
        assert log._dim("hi") == "hi"
        assert log._bold("hi") == "hi"


# =============================================================================
# Output functions
# =============================================================================

class TestOutputFunctions:
    def test_info(self, capsys):
        log.info("hello")
        assert "hello" in capsys.readouterr().out

    def test_detail_verbose(self, capsys):
        log._verbose = True
        log.detail("verbose msg")
        assert "verbose msg" in capsys.readouterr().out

    def test_detail_not_verbose(self, capsys):
        log._verbose = False
        log.detail("hidden")
        assert capsys.readouterr().out == ""

    def test_success(self, capsys):
        log._color = False
        log.success("done")
        assert "done" in capsys.readouterr().out

    def test_warn(self, capsys):
        log._color = False
        log.warn("careful")
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "careful" in out

    def test_error(self, capsys):
        log._color = False
        log.error("broken")
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "broken" in err

    def test_step(self, capsys):
        log._color = False
        log.step("board_health", "checking")
        out = capsys.readouterr().out
        assert "board_health" in out
        assert "checking" in out

    def test_step_detail_verbose(self, capsys):
        log._verbose = True
        log._color = False
        log.step_detail("sync", "detail info")
        out = capsys.readouterr().out
        assert "sync" in out
        assert "detail info" in out

    def test_step_detail_not_verbose(self, capsys):
        log._verbose = False
        log.step_detail("sync", "hidden")
        assert capsys.readouterr().out == ""

    def test_header(self, capsys):
        log._color = False
        log.header("My Section")
        out = capsys.readouterr().out
        assert "My Section" in out

    def test_banner(self, capsys):
        log._color = False
        log.banner(["Line 1", "Line 2"])
        out = capsys.readouterr().out
        assert "Line 1" in out
        assert "Line 2" in out

    def test_progress(self, capsys):
        log._color = False
        log.progress("Dev1", 1, 5)
        out = capsys.readouterr().out
        assert "Dev1" in out
        assert "1/5" in out

    def test_progress_with_emoji(self, capsys):
        log._color = False
        log.progress("Dev1", 2, 5, emoji="X")
        out = capsys.readouterr().out
        assert "X Dev1" in out

    def test_agent_done(self, capsys):
        log._color = False
        log.agent_done("Dev1", 3, 45.0)
        out = capsys.readouterr().out
        assert "done" in out
        assert "3 files" in out
        assert "45s" in out

    def test_agent_done_minutes(self, capsys):
        log._color = False
        log.agent_done("Dev1", 1, 120.0)
        out = capsys.readouterr().out
        assert "2.0m" in out

    def test_agent_error(self, capsys):
        log._color = False
        log.agent_error("Dev1", "something broke")
        out = capsys.readouterr().out
        assert "failed" in out
        assert "something broke" in out

    def test_agent_retry(self, capsys):
        log._color = False
        log.agent_retry(30)
        out = capsys.readouterr().out
        assert "retrying" in out
        assert "30s" in out


# =============================================================================
# JsonFormatter
# =============================================================================

class TestJsonFormatter:
    def test_basic_format(self):
        formatter = log.JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "hello world"
        assert data["logger"] == "test"
        assert "timestamp" in data

    def test_includes_extra_fields(self):
        formatter = log.JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        record.custom_field = "custom_value"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["custom_field"] == "custom_value"

    def test_includes_exception(self):
        formatter = log.JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="error", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_includes_stack_info(self):
        formatter = log.JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        record.stack_info = "some stack trace"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["stack_info"] == "some stack trace"


# =============================================================================
# wants_json_logging / setup_json_logging
# =============================================================================

class TestJsonLogging:
    @patch.dict(os.environ, {"OPENSEPIA_LOG_FORMAT": "json"})
    def test_wants_json_true(self):
        assert log.wants_json_logging() is True

    @patch.dict(os.environ, {}, clear=True)
    def test_wants_json_false_when_unset(self):
        os.environ.pop("OPENSEPIA_LOG_FORMAT", None)
        assert log.wants_json_logging() is False

    def test_setup_json_logging(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        log.setup_json_logging(log_file)

        test_logger = logging.getLogger("test_json_setup")
        test_logger.info("json test message")

        content = (tmp_path / "test.log").read_text(encoding="utf-8")
        data = json.loads(content.strip())
        assert data["message"] == "json test message"

        # Cleanup
        logging.getLogger().handlers.clear()
