"""Tests for SEC-025: Secret value read from prompt instead of CLI argument."""

from unittest.mock import patch

from click.testing import CliRunner

from clouddeploy.cli import cli


class TestSecretsSetPrompt:
    """Verify secrets set reads value securely when not passed as argument."""

    def test_value_as_argument_still_works(self, tmp_path):
        """Backwards-compatible: passing value as argument should still work."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--db", str(tmp_path / "state.db"),
            "secrets", "set", "dev", "MY_KEY", "my_value",
        ])
        assert result.exit_code == 0
        assert "Secret set" in result.output

    def test_prompts_when_value_omitted(self, tmp_path):
        """When value is omitted, should prompt for hidden input."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--db", str(tmp_path / "state.db"),
            "secrets", "set", "dev", "MY_KEY",
        ], input="secret_from_prompt\n")
        assert result.exit_code == 0
        assert "Secret set" in result.output

    def test_reads_from_stdin_pipe(self, tmp_path):
        """When stdin is piped (not a tty), should read value from stdin."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--db", str(tmp_path / "state.db"),
            "secrets", "set", "dev", "MY_KEY",
        ], input="piped_secret\n")
        assert result.exit_code == 0
        assert "Secret set" in result.output