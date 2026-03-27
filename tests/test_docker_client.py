#!/usr/bin/env python3
"""Comprehensive unit tests for opensepia.integrations.docker_client."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from opensepia.integrations.docker_client import DockerClient, DockerConfig
from opensepia.config import (
    DOCKER_CMD_TIMEOUT,
    DOCKER_COMPOSE_TIMEOUT,
    DOCKER_BUILD_TIMEOUT,
    DOCKER_TRANSFER_TIMEOUT,
    DOCKER_LOGIN_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# DockerConfig tests
# ---------------------------------------------------------------------------

class TestDockerConfig:

    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = DockerConfig()
        assert cfg.docker_host == ""
        assert cfg.registry == ""
        assert cfg.registry_user == ""
        assert cfg.registry_pass == ""
        assert cfg.image_prefix == ""
        assert cfg.compose_file == "docker-compose.yml"
        assert cfg.max_containers == 10
        assert cfg.allowed_networks == ["bridge", "host"]
        assert cfg.is_configured is True

    def test_env_var_loading(self):
        env = {
            "DOCKER_HOST": "tcp://192.168.1.10:2375",
            "DOCKER_REGISTRY": "registry.example.com",
            "DOCKER_REGISTRY_USER": "admin",
            "DOCKER_REGISTRY_PASS": "secret",
            "DOCKER_IMAGE_PREFIX": "myorg/",
            "DOCKER_COMPOSE_FILE": "compose.prod.yml",
            "DOCKER_MAX_CONTAINERS": "5",
            "DOCKER_ALLOWED_NETWORKS": "bridge,custom_net",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = DockerConfig()
        assert cfg.docker_host == "tcp://192.168.1.10:2375"
        assert cfg.registry == "registry.example.com"
        assert cfg.registry_user == "admin"
        assert cfg.registry_pass == "secret"
        assert cfg.image_prefix == "myorg/"
        assert cfg.compose_file == "compose.prod.yml"
        assert cfg.max_containers == 5
        assert cfg.allowed_networks == ["bridge", "custom_net"]

    def test_max_containers_invalid_string_defaults_to_10(self):
        with patch.dict(os.environ, {"DOCKER_MAX_CONTAINERS": "abc"}, clear=True):
            cfg = DockerConfig()
        assert cfg.max_containers == 10

    def test_max_containers_negative_defaults_to_10(self):
        with patch.dict(os.environ, {"DOCKER_MAX_CONTAINERS": "-3"}, clear=True):
            cfg = DockerConfig()
        assert cfg.max_containers == 10

    def test_max_containers_zero_defaults_to_10(self):
        with patch.dict(os.environ, {"DOCKER_MAX_CONTAINERS": "0"}, clear=True):
            cfg = DockerConfig()
        assert cfg.max_containers == 10


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    with patch.dict(os.environ, {}, clear=True):
        return DockerConfig()


@pytest.fixture
def client(config):
    return DockerClient(config=config)


# ---------------------------------------------------------------------------
# _parse_json_lines
# ---------------------------------------------------------------------------

class TestParseJsonLines:

    def test_single_line(self, client):
        result = client._parse_json_lines('{"a":1}\n')
        assert result == [{"a": 1}]

    def test_multiple_lines(self, client):
        text = '{"a":1}\n{"b":2}\n{"c":3}\n'
        result = client._parse_json_lines(text)
        assert len(result) == 3
        assert result[1] == {"b": 2}

    def test_empty_string(self, client):
        assert client._parse_json_lines("") == []

    def test_blank_lines_skipped(self, client):
        result = client._parse_json_lines('{"a":1}\n\n{"b":2}\n\n')
        assert len(result) == 2

    def test_invalid_json_skipped(self, client):
        text = '{"a":1}\nNOT_JSON\n{"b":2}\n'
        result = client._parse_json_lines(text)
        assert len(result) == 2

    def test_all_invalid(self, client):
        assert client._parse_json_lines("bad\nworse\n") == []


# ---------------------------------------------------------------------------
# _run internals
# ---------------------------------------------------------------------------

class TestRunInternal:

    @patch("subprocess.run")
    def test_run_passes_docker_host(self, mock_run):
        cfg = DockerConfig()
        cfg.docker_host = "tcp://remote:2375"
        c = DockerClient(config=cfg)
        mock_run.return_value = _completed()
        c._run("ps")
        _, kwargs = mock_run.call_args
        assert kwargs["env"]["DOCKER_HOST"] == "tcp://remote:2375"

    @patch("subprocess.run")
    def test_run_no_docker_host(self, mock_run, client):
        mock_run.return_value = _completed()
        client._run("ps")
        _, kwargs = mock_run.call_args
        assert "DOCKER_HOST" not in kwargs["env"] or kwargs["env"].get("DOCKER_HOST", "") == ""

    @patch("subprocess.run")
    def test_run_timeout_default(self, mock_run, client):
        mock_run.return_value = _completed()
        client._run("ps")
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == DOCKER_CMD_TIMEOUT

    @patch("subprocess.run")
    def test_run_custom_timeout(self, mock_run, client):
        mock_run.return_value = _completed()
        client._run("build", ".", timeout=999)
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 999


# ---------------------------------------------------------------------------
# ps
# ---------------------------------------------------------------------------

class TestPs:

    @patch("subprocess.run")
    def test_ps_success(self, mock_run, client):
        mock_run.return_value = _completed(stdout='{"Names":"web","State":"running"}\n')
        result = client.ps()
        assert len(result) == 1
        assert result[0]["Names"] == "web"

    @patch("subprocess.run")
    def test_ps_all_flag(self, mock_run, client):
        mock_run.return_value = _completed(stdout='{"Names":"web"}\n{"Names":"old"}\n')
        client.ps(all=True)
        args_used = mock_run.call_args[0][0]
        assert "-a" in args_used

    @patch("subprocess.run")
    def test_ps_failure_returns_empty(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="error")
        assert client.ps() == []


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

class TestInspect:

    @patch("subprocess.run")
    def test_inspect_success(self, mock_run, client):
        data = [{"Id": "abc123", "State": {"Running": True}}]
        mock_run.return_value = _completed(stdout=json.dumps(data))
        result = client.inspect("mycontainer")
        assert result["Id"] == "abc123"

    @patch("subprocess.run")
    def test_inspect_empty_list(self, mock_run, client):
        mock_run.return_value = _completed(stdout="[]")
        assert client.inspect("missing") == {}

    @patch("subprocess.run")
    def test_inspect_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="not found")
        result = client.inspect("bad")
        assert result == {"error": "not found"}


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

class TestLogs:

    @patch("subprocess.run")
    def test_logs_basic(self, mock_run, client):
        mock_run.return_value = _completed(stdout="line1\n", stderr="line2\n")
        result = client.logs("web")
        assert "line1" in result
        assert "line2" in result

    @patch("subprocess.run")
    def test_logs_tail(self, mock_run, client):
        mock_run.return_value = _completed()
        client.logs("web", tail=50)
        args_used = mock_run.call_args[0][0]
        assert "--tail=50" in args_used

    @patch("subprocess.run")
    def test_logs_since(self, mock_run, client):
        mock_run.return_value = _completed()
        client.logs("web", since="1h")
        args_used = mock_run.call_args[0][0]
        assert "--since=1h" in args_used


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestStats:

    @patch("subprocess.run")
    def test_stats_all(self, mock_run, client):
        mock_run.return_value = _completed(stdout="NAME\tCPU\nweb\t1%\n")
        result = client.stats()
        assert "web" in result

    @patch("subprocess.run")
    def test_stats_specific_container(self, mock_run, client):
        mock_run.return_value = _completed(stdout="web\t2%\n")
        client.stats(container="web")
        args_used = mock_run.call_args[0][0]
        assert "web" in args_used


# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------

class TestImages:

    @patch("subprocess.run")
    def test_images_success(self, mock_run, client):
        mock_run.return_value = _completed(stdout='{"Repository":"nginx","Tag":"latest"}\n')
        result = client.images()
        assert len(result) == 1
        assert result[0]["Repository"] == "nginx"

    @patch("subprocess.run")
    def test_images_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1)
        assert client.images() == []


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

class TestBuild:

    @patch("subprocess.run")
    def test_build_simple(self, mock_run, client):
        mock_run.return_value = _completed(stdout="Successfully built abc123")
        result = client.build()
        assert result["success"] is True
        assert result["tag"] is None

    @patch("subprocess.run")
    def test_build_with_tag(self, mock_run, client):
        mock_run.return_value = _completed(stdout="OK")
        client.build(tag="myapp:v1")
        args_used = mock_run.call_args[0][0]
        assert "-t" in args_used
        assert "myapp:v1" in args_used

    @patch("subprocess.run")
    def test_build_with_image_prefix(self, mock_run):
        cfg = DockerConfig()
        cfg.image_prefix = "org/"
        c = DockerClient(config=cfg)
        mock_run.return_value = _completed(stdout="OK")
        c.build(tag="myapp:v1")
        args_used = mock_run.call_args[0][0]
        assert "org/myapp:v1" in args_used

    @patch("subprocess.run")
    def test_build_with_dockerfile(self, mock_run, client):
        mock_run.return_value = _completed()
        client.build(dockerfile="Dockerfile.prod")
        args_used = mock_run.call_args[0][0]
        assert "-f" in args_used
        assert "Dockerfile.prod" in args_used

    @patch("subprocess.run")
    def test_build_no_cache(self, mock_run, client):
        mock_run.return_value = _completed()
        client.build(no_cache=True)
        args_used = mock_run.call_args[0][0]
        assert "--no-cache" in args_used

    @patch("subprocess.run")
    def test_build_with_build_args(self, mock_run, client):
        mock_run.return_value = _completed()
        client.build(build_args={"NODE_ENV": "production"})
        args_used = mock_run.call_args[0][0]
        assert "--build-arg" in args_used
        assert "NODE_ENV=production" in args_used

    @patch("subprocess.run")
    def test_build_uses_build_timeout(self, mock_run, client):
        mock_run.return_value = _completed()
        client.build()
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == DOCKER_BUILD_TIMEOUT

    @patch("subprocess.run")
    def test_build_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="build error")
        result = client.build()
        assert result["success"] is False
        assert result["error"] == "build error"

    @patch("subprocess.run")
    def test_build_output_truncated(self, mock_run, client):
        big_output = "x" * 5000
        mock_run.return_value = _completed(stdout=big_output)
        result = client.build()
        assert len(result["output"]) == 2000


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

class TestRun:

    @patch("subprocess.run")
    def test_run_success(self, mock_run, client):
        # First call: ps (container limit check), second call: run
        mock_run.side_effect = [
            _completed(stdout=""),  # ps returns empty
            _completed(stdout="abcdef123456789\n"),  # run returns container ID
        ]
        result = client.run(image="nginx", name="web")
        assert result["success"] is True
        assert result["container_id"] == "abcdef123456"
        assert result["name"] == "web"

    @patch("subprocess.run")
    def test_run_container_limit_reached(self, mock_run):
        cfg = DockerConfig()
        cfg.max_containers = 2
        c = DockerClient(config=cfg)
        # ps returns 2 containers
        ps_output = '{"Names":"a"}\n{"Names":"b"}\n'
        mock_run.return_value = _completed(stdout=ps_output)
        result = c.run(image="nginx")
        assert "error" in result
        assert "limit" in result["error"].lower()

    @patch("subprocess.run")
    def test_run_disallowed_network(self, mock_run, client):
        mock_run.return_value = _completed(stdout="")  # ps
        result = client.run(image="nginx", network="evil_net")
        assert "error" in result
        assert "not allowed" in result["error"]

    @patch("subprocess.run")
    def test_run_allowed_network(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),
            _completed(stdout="container_id_123\n"),
        ]
        result = client.run(image="nginx", network="bridge")
        assert result["success"] is True

    @patch("subprocess.run")
    def test_run_with_ports_volumes_env_labels(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),
            _completed(stdout="cid123\n"),
        ]
        client.run(
            image="nginx",
            ports={"8080": "80"},
            volumes={"/data": "/app/data"},
            env={"NODE_ENV": "prod"},
            labels={"tier": "frontend"},
        )
        args_used = mock_run.call_args_list[1][0][0]
        assert "-p" in args_used
        assert "8080:80" in args_used
        assert "-v" in args_used
        assert "/data:/app/data" in args_used
        assert "-e" in args_used
        assert "NODE_ENV=prod" in args_used
        assert "--label" in args_used
        assert "tier=frontend" in args_used
        # managed-by label always added
        assert "managed-by=ai-team" in args_used

    @patch("subprocess.run")
    def test_run_with_command(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),
            _completed(stdout="cid\n"),
        ]
        client.run(image="alpine", command="echo hello world")
        args_used = mock_run.call_args_list[1][0][0]
        assert "echo" in args_used
        assert "hello" in args_used

    @patch("subprocess.run")
    def test_run_detach_false(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),
            _completed(stdout="cid\n"),
        ]
        client.run(image="alpine", detach=False)
        args_used = mock_run.call_args_list[1][0][0]
        assert "-d" not in args_used

    @patch("subprocess.run")
    def test_run_failure(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),
            _completed(returncode=1, stderr="conflict"),
        ]
        result = client.run(image="nginx")
        assert result["success"] is False
        assert "conflict" in result["error"]


# ---------------------------------------------------------------------------
# stop / start / restart / rm
# ---------------------------------------------------------------------------

class TestLifecycle:

    @patch("subprocess.run")
    def test_stop_success(self, mock_run, client):
        mock_run.return_value = _completed()
        result = client.stop("web")
        assert result["success"] is True
        assert result["error"] == ""

    @patch("subprocess.run")
    def test_stop_custom_timeout(self, mock_run, client):
        mock_run.return_value = _completed()
        client.stop("web", timeout=30)
        args_used = mock_run.call_args[0][0]
        assert "-t" in args_used
        assert "30" in args_used

    @patch("subprocess.run")
    def test_stop_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="no such container")
        result = client.stop("ghost")
        assert result["success"] is False
        assert "no such container" in result["error"]

    @patch("subprocess.run")
    def test_start_success(self, mock_run, client):
        mock_run.return_value = _completed()
        assert client.start("web")["success"] is True

    @patch("subprocess.run")
    def test_start_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="error")
        result = client.start("bad")
        assert result["success"] is False

    @patch("subprocess.run")
    def test_restart_success(self, mock_run, client):
        mock_run.return_value = _completed()
        assert client.restart("web")["success"] is True

    @patch("subprocess.run")
    def test_restart_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="fail")
        result = client.restart("bad")
        assert result["success"] is False

    @patch("subprocess.run")
    def test_rm_success(self, mock_run, client):
        mock_run.return_value = _completed()
        assert client.rm("web")["success"] is True

    @patch("subprocess.run")
    def test_rm_force(self, mock_run, client):
        mock_run.return_value = _completed()
        client.rm("web", force=True)
        args_used = mock_run.call_args[0][0]
        assert "-f" in args_used

    @patch("subprocess.run")
    def test_rm_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="running")
        result = client.rm("web")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# pull / push / login
# ---------------------------------------------------------------------------

class TestPullPush:

    @patch("subprocess.run")
    def test_pull_success(self, mock_run, client):
        mock_run.return_value = _completed()
        result = client.pull("nginx:latest")
        assert result["success"] is True
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == DOCKER_TRANSFER_TIMEOUT

    @patch("subprocess.run")
    def test_pull_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="not found")
        result = client.pull("bad:image")
        assert result["success"] is False

    @patch("subprocess.run")
    def test_push_no_credentials(self, mock_run, client):
        mock_run.return_value = _completed()
        result = client.push("myimage:v1")
        assert result["success"] is True
        # Only one call (push), no login
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_push_with_login_success(self, mock_run):
        cfg = DockerConfig()
        cfg.registry = "reg.io"
        cfg.registry_user = "user"
        cfg.registry_pass = "pass"
        c = DockerClient(config=cfg)
        mock_run.side_effect = [
            _completed(),  # login
            _completed(),  # push
        ]
        result = c.push("myimage:v1")
        assert result["success"] is True
        assert mock_run.call_count == 2
        # First call is login with --password-stdin
        login_call = mock_run.call_args_list[0]
        assert login_call[1].get("input") == "pass" or login_call[0][0][-1] == "--password-stdin"

    @patch("subprocess.run")
    def test_push_login_failure(self, mock_run):
        cfg = DockerConfig()
        cfg.registry = "reg.io"
        cfg.registry_user = "user"
        cfg.registry_pass = "pass"
        c = DockerClient(config=cfg)
        mock_run.return_value = _completed(returncode=1, stderr="auth denied")
        result = c.push("myimage:v1")
        assert result["success"] is False
        assert "Login failed" in result["error"]
        # Should not attempt push after failed login
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_push_login_uses_login_timeout(self, mock_run):
        cfg = DockerConfig()
        cfg.registry = "reg.io"
        cfg.registry_user = "user"
        cfg.registry_pass = "pass"
        c = DockerClient(config=cfg)
        mock_run.side_effect = [
            _completed(),  # login
            _completed(),  # push
        ]
        c.push("img:v1")
        login_kwargs = mock_run.call_args_list[0][1]
        assert login_kwargs["timeout"] == DOCKER_LOGIN_TIMEOUT

    @patch("subprocess.run")
    def test_push_with_docker_host(self, mock_run):
        cfg = DockerConfig()
        cfg.docker_host = "tcp://remote:2375"
        cfg.registry_user = "u"
        cfg.registry_pass = "p"
        cfg.registry = "r"
        c = DockerClient(config=cfg)
        mock_run.side_effect = [_completed(), _completed()]
        c.push("img")
        login_kwargs = mock_run.call_args_list[0][1]
        assert login_kwargs["env"]["DOCKER_HOST"] == "tcp://remote:2375"


# ---------------------------------------------------------------------------
# Compose methods
# ---------------------------------------------------------------------------

class TestCompose:

    @patch("subprocess.run")
    def test_compose_up_basic(self, mock_run, client):
        mock_run.return_value = _completed(stdout="started")
        result = client.compose_up()
        assert result["success"] is True
        args_used = mock_run.call_args[0][0]
        assert args_used[:2] == ["docker", "compose"]
        assert "up" in args_used
        assert "-d" in args_used

    @patch("subprocess.run")
    def test_compose_up_with_build_and_services(self, mock_run, client):
        mock_run.return_value = _completed(stdout="ok")
        client.compose_up(services=["web", "db"], build=True)
        args_used = mock_run.call_args[0][0]
        assert "--build" in args_used
        assert "web" in args_used
        assert "db" in args_used

    @patch("subprocess.run")
    def test_compose_up_no_detach(self, mock_run, client):
        mock_run.return_value = _completed()
        client.compose_up(detach=False)
        args_used = mock_run.call_args[0][0]
        assert "-d" not in args_used

    @patch("subprocess.run")
    def test_compose_up_with_cwd(self, mock_run, client, tmp_path):
        mock_run.return_value = _completed()
        client.compose_up(cwd=tmp_path)
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == str(tmp_path)

    @patch("subprocess.run")
    def test_compose_up_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="error")
        result = client.compose_up()
        assert result["success"] is False
        assert result["error"] == "error"

    @patch("subprocess.run")
    def test_compose_down_basic(self, mock_run, client):
        mock_run.return_value = _completed()
        result = client.compose_down()
        assert result["success"] is True
        args_used = mock_run.call_args[0][0]
        assert "down" in args_used

    @patch("subprocess.run")
    def test_compose_down_with_volumes(self, mock_run, client):
        mock_run.return_value = _completed()
        client.compose_down(volumes=True)
        args_used = mock_run.call_args[0][0]
        assert "-v" in args_used

    @patch("subprocess.run")
    def test_compose_down_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="fail")
        result = client.compose_down()
        assert result["success"] is False

    @patch("subprocess.run")
    def test_compose_ps(self, mock_run, client):
        mock_run.return_value = _completed(stdout="NAME\tSTATUS\nweb\tUp\n")
        result = client.compose_ps()
        assert "web" in result

    @patch("subprocess.run")
    def test_compose_ps_with_cwd(self, mock_run, client, tmp_path):
        mock_run.return_value = _completed(stdout="output")
        client.compose_ps(cwd=tmp_path)
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == str(tmp_path)

    @patch("subprocess.run")
    def test_compose_logs_basic(self, mock_run, client):
        mock_run.return_value = _completed(stdout="log line\n", stderr="err line\n")
        result = client.compose_logs()
        assert "log line" in result
        assert "err line" in result

    @patch("subprocess.run")
    def test_compose_logs_with_services_and_tail(self, mock_run, client):
        mock_run.return_value = _completed()
        client.compose_logs(services=["web"], tail=50)
        args_used = mock_run.call_args[0][0]
        assert "--tail=50" in args_used
        assert "web" in args_used

    @patch("subprocess.run")
    def test_compose_uses_compose_timeout(self, mock_run, client):
        mock_run.return_value = _completed()
        client.compose_up()
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == DOCKER_COMPOSE_TIMEOUT

    @patch("subprocess.run")
    def test_compose_restart_basic(self, mock_run, client):
        mock_run.return_value = _completed()
        result = client.compose_restart()
        assert result["success"] is True
        args_used = mock_run.call_args[0][0]
        assert "restart" in args_used

    @patch("subprocess.run")
    def test_compose_restart_with_services(self, mock_run, client):
        mock_run.return_value = _completed()
        client.compose_restart(services=["web", "worker"])
        args_used = mock_run.call_args[0][0]
        assert "web" in args_used
        assert "worker" in args_used

    @patch("subprocess.run")
    def test_compose_docker_host_forwarded(self, mock_run):
        cfg = DockerConfig()
        cfg.docker_host = "tcp://host:2375"
        c = DockerClient(config=cfg)
        mock_run.return_value = _completed()
        c.compose_up()
        _, kwargs = mock_run.call_args
        assert kwargs["env"]["DOCKER_HOST"] == "tcp://host:2375"


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------

class TestDeploy:

    @patch("subprocess.run")
    def test_deploy_no_build(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),                      # check existing (ps -aq)
            _completed(stdout=""),                      # ps for run limit check
            _completed(stdout="new_container_id\n"),    # run
        ]
        result = client.deploy(image="nginx", name="web")
        assert result["built"] is False
        assert result["started_new"] is True
        assert result["errors"] == []

    @patch("subprocess.run")
    def test_deploy_with_build(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout="built"),                  # build
            _completed(stdout=""),                       # check existing
            _completed(stdout=""),                       # ps for limit
            _completed(stdout="new_id\n"),               # run
        ]
        result = client.deploy(image="myapp", name="app", build_path="/code")
        assert result["built"] is True
        assert result["started_new"] is True

    @patch("subprocess.run")
    def test_deploy_build_failure(self, mock_run, client):
        mock_run.return_value = _completed(returncode=1, stderr="build err")
        result = client.deploy(image="myapp", name="app", build_path="/code")
        assert result["built"] is False
        assert result["started_new"] is False
        assert len(result["errors"]) == 1
        assert "Build failed" in result["errors"][0]

    @patch("subprocess.run")
    def test_deploy_stops_existing(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout="oldcontainerid\n"),    # check existing -> found
            _completed(),                              # stop
            _completed(),                              # rm
            _completed(stdout=""),                      # ps for limit
            _completed(stdout="newid\n"),               # run
        ]
        result = client.deploy(image="nginx", name="web")
        assert result["stopped_old"] is True
        assert result["started_new"] is True

    @patch("subprocess.run")
    def test_deploy_run_failure(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),                      # check existing
            _completed(stdout=""),                      # ps for limit
            _completed(returncode=1, stderr="port conflict"),  # run fails
        ]
        result = client.deploy(image="nginx", name="web")
        assert result["started_new"] is False
        assert any("Run failed" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# get_docker_context_md
# ---------------------------------------------------------------------------

class TestGetDockerContextMd:

    @patch("subprocess.run")
    def test_context_md_with_containers(self, mock_run, client):
        ps_out = '{"Names":"web","State":"running","Image":"nginx","Status":"Up 2h","Ports":"80/tcp"}\n'
        ps_out += '{"Names":"old","State":"exited","Image":"redis","Status":"Exited (0)"}\n'
        stats_out = "NAME\tCPU\nweb\t1.5%\n"
        images_out = '{"Repository":"nginx","Tag":"latest","Size":"150MB"}\n'
        mock_run.side_effect = [
            _completed(stdout=ps_out),    # ps(all=True)
            _completed(stdout=stats_out), # stats()
            _completed(stdout=images_out),# images()
        ]
        md = client.get_docker_context_md()
        assert "Running containers (1)" in md
        assert "**web**" in md
        assert "Stopped containers (1)" in md
        assert "old" in md
        assert "nginx:latest" in md

    @patch("subprocess.run")
    def test_context_md_no_containers(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),   # ps
            _completed(stdout=""),   # stats
            _completed(stdout=""),   # images (empty -> returncode 0 but empty)
        ]
        md = client.get_docker_context_md()
        assert "Running containers (0)" in md
        assert "_(none)_" in md


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    @patch("subprocess.run")
    def test_inspect_json_parse_error(self, mock_run, client):
        mock_run.return_value = _completed(stdout="NOT JSON")
        # inspect tries json.loads on stdout when returncode==0
        # This should raise, but let's verify
        with pytest.raises(json.JSONDecodeError):
            client.inspect("container")

    @patch("subprocess.run")
    def test_run_nonzero_exit_code(self, mock_run, client):
        mock_run.side_effect = [
            _completed(stdout=""),
            _completed(returncode=125, stderr="docker daemon error"),
        ]
        result = client.run(image="bad")
        assert result["success"] is False

    def test_client_default_config(self):
        """DockerClient creates a default config if none provided."""
        with patch.dict(os.environ, {}, clear=True):
            c = DockerClient()
        assert isinstance(c.config, DockerConfig)
        assert c.config.max_containers == 10
