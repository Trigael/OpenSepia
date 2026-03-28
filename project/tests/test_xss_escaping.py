"""Tests for SEC-023: XSS prevention in dashboard templates."""

from html import escape

from clouddeploy.dashboard.templates import render_index, _status_badge


class TestXSSEscaping:
    """Verify that malicious content is HTML-escaped in rendered output."""

    XSS_PAYLOAD = '<img src=x onerror=alert(1)>'

    def test_deployment_id_escaped(self):
        deps = [{"id": self.XSS_PAYLOAD, "environment": "dev", "status": "succeeded",
                 "image": "x", "version": "1", "commit_sha": "abc",
                 "created_at": "t", "finished_at": "t", "message": ""}]
        html = render_index(deps, [], ["dev"], {"total": 1, "succeeded": 1, "failed": 0})
        assert self.XSS_PAYLOAD not in html
        assert escape(self.XSS_PAYLOAD) in html

    def test_deployment_image_escaped(self):
        deps = [{"id": "d1", "environment": "dev", "status": "succeeded",
                 "image": self.XSS_PAYLOAD, "version": "1", "commit_sha": "abc",
                 "created_at": "t", "finished_at": "t", "message": ""}]
        html = render_index(deps, [], ["dev"], {"total": 1, "succeeded": 1, "failed": 0})
        assert self.XSS_PAYLOAD not in html

    def test_deployment_message_escaped(self):
        deps = [{"id": "d1", "environment": "dev", "status": "succeeded",
                 "image": "x", "version": "1", "commit_sha": "abc",
                 "created_at": "t", "finished_at": "t", "message": self.XSS_PAYLOAD}]
        html = render_index(deps, [], ["dev"], {"total": 1, "succeeded": 1, "failed": 0})
        assert self.XSS_PAYLOAD not in html

    def test_deployment_commit_sha_escaped(self):
        deps = [{"id": "d1", "environment": "dev", "status": "succeeded",
                 "image": "x", "version": "1", "commit_sha": self.XSS_PAYLOAD,
                 "created_at": "t", "finished_at": "t", "message": ""}]
        html = render_index(deps, [], ["dev"], {"total": 1, "succeeded": 1, "failed": 0})
        assert self.XSS_PAYLOAD not in html

    def test_health_check_app_escaped(self):
        hcs = [{"app": self.XSS_PAYLOAD, "environment": "dev", "healthy": True,
                "endpoint": "/health", "attempts": 1, "elapsed_seconds": 1.0,
                "checked_at": "t", "message": "ok"}]
        html = render_index([], hcs, [], {"total": 0, "succeeded": 0, "failed": 0})
        assert self.XSS_PAYLOAD not in html

    def test_health_check_endpoint_escaped(self):
        hcs = [{"app": "myapp", "environment": "dev", "healthy": True,
                "endpoint": self.XSS_PAYLOAD, "attempts": 1, "elapsed_seconds": 1.0,
                "checked_at": "t", "message": "ok"}]
        html = render_index([], hcs, [], {"total": 0, "succeeded": 0, "failed": 0})
        assert self.XSS_PAYLOAD not in html

    def test_health_check_message_escaped(self):
        hcs = [{"app": "myapp", "environment": "dev", "healthy": True,
                "endpoint": "/health", "attempts": 1, "elapsed_seconds": 1.0,
                "checked_at": "t", "message": self.XSS_PAYLOAD}]
        html = render_index([], hcs, [], {"total": 0, "succeeded": 0, "failed": 0})
        assert self.XSS_PAYLOAD not in html

    def test_status_badge_escaped(self):
        html = _status_badge('<script>alert(1)</script>')
        assert '<script>' not in html
        assert '&lt;script&gt;' in html