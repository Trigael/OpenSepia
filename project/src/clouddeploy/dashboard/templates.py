"""Inline HTML templates for the CloudDeploy dashboard.

Keeps the dashboard self-contained with no external template files or
static asset dependencies.
"""

from html import escape as _esc

STATUS_COLORS = {
    "succeeded": "#22c55e",
    "failed": "#ef4444",
    "pending": "#eab308",
    "running": "#3b82f6",
    "rolling_back": "#f59e0b",
    "rolled_back": "#a855f7",
}

HEALTH_COLORS = {
    True: "#22c55e",
    False: "#ef4444",
}


def _status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#6b7280")
    return f'<span class="badge" style="background:{color}">{_esc(status)}</span>'


def _health_badge(healthy: bool) -> str:
    color = HEALTH_COLORS[healthy]
    label = "healthy" if healthy else "unhealthy"
    return f'<span class="badge" style="background:{color}">{label}</span>'


BASE_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0f172a; color: #e2e8f0; }
.container { max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
header { display: flex; align-items: center; justify-content: space-between;
         margin-bottom: 2rem; border-bottom: 1px solid #1e293b; padding-bottom: 1rem; }
header h1 { font-size: 1.5rem; }
header .live { font-size: 0.85rem; color: #22c55e; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
         gap: 1rem; margin-bottom: 2rem; }
.card { background: #1e293b; border-radius: 0.5rem; padding: 1.25rem; }
.card h3 { font-size: 0.8rem; text-transform: uppercase; color: #94a3b8;
           margin-bottom: 0.5rem; }
.card .value { font-size: 1.75rem; font-weight: 700; }
table { width: 100%; border-collapse: collapse; background: #1e293b;
        border-radius: 0.5rem; overflow: hidden; }
th { text-align: left; padding: 0.75rem 1rem; background: #334155;
     font-size: 0.8rem; text-transform: uppercase; color: #94a3b8; }
td { padding: 0.75rem 1rem; border-top: 1px solid #334155; font-size: 0.9rem; }
tr:hover td { background: #1e3a5f; }
.badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 9999px;
         font-size: 0.75rem; font-weight: 600; color: #fff; }
.section { margin-bottom: 2rem; }
.section h2 { font-size: 1.1rem; margin-bottom: 0.75rem; }
.env-tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
.env-tab { padding: 0.4rem 1rem; border-radius: 0.375rem; cursor: pointer;
           background: #334155; border: none; color: #e2e8f0; font-size: 0.85rem; }
.env-tab.active { background: #3b82f6; }
.empty { color: #64748b; font-style: italic; padding: 1rem; }
.health-bar { display: flex; gap: 3px; align-items: center; }
.health-dot { width: 12px; height: 12px; border-radius: 50%; }
.mono { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.85rem; }
"""

SSE_SCRIPT = """\
<script>
const evtSource = new EventSource("/api/events");
evtSource.onmessage = function(event) {
  const data = JSON.parse(event.data);
  if (data.type === "refresh") {
    location.reload();
  }
};
evtSource.onerror = function() {
  document.getElementById("live-indicator").textContent = "disconnected";
  document.getElementById("live-indicator").style.color = "#ef4444";
};

// Environment tab switching
document.addEventListener("DOMContentLoaded", function() {
  document.querySelectorAll(".env-tab").forEach(function(tab) {
    tab.addEventListener("click", function() {
      const env = this.dataset.env;
      document.querySelectorAll(".env-tab").forEach(t => t.classList.remove("active"));
      this.classList.add("active");
      document.querySelectorAll(".env-panel").forEach(p => p.style.display = "none");
      const panel = document.getElementById("env-" + env);
      if (panel) panel.style.display = "block";
    });
  });
});
</script>
"""


def render_index(
    deployments: list[dict],
    health_checks: list[dict],
    environments: list[str],
    summary: dict,
) -> str:
    """Render the main dashboard page."""
    # Summary cards
    cards = f"""\
    <div class="cards">
      <div class="card">
        <h3>Total Deployments</h3>
        <div class="value">{int(summary.get('total', 0))}</div>
      </div>
      <div class="card">
        <h3>Succeeded</h3>
        <div class="value" style="color:#22c55e">{int(summary.get('succeeded', 0))}</div>
      </div>
      <div class="card">
        <h3>Failed</h3>
        <div class="value" style="color:#ef4444">{int(summary.get('failed', 0))}</div>
      </div>
      <div class="card">
        <h3>Environments</h3>
        <div class="value">{len(environments)}</div>
      </div>
    </div>"""

    # Environment tabs
    env_tabs = ""
    if environments:
        tabs = []
        for i, env in enumerate(environments):
            active = ' class="env-tab active"' if i == 0 else ' class="env-tab"'
            tabs.append(f'<button{active} data-env="{_esc(env)}">{_esc(env)}</button>')
        env_tabs = f'<div class="env-tabs">{"".join(tabs)}</div>'

    # Deployment tables per environment
    env_panels = []
    for i, env in enumerate(environments):
        display = "block" if i == 0 else "none"
        env_deps = [d for d in deployments if d["environment"] == env]
        if env_deps:
            rows = []
            for d in env_deps:
                sha = _esc((d.get("commit_sha", "") or "")[:8] or "-")
                rows.append(
                    f"<tr><td class='mono'>{_esc(str(d['id']))}</td>"
                    f"<td>{_status_badge(d['status'])}</td>"
                    f"<td>{_esc(d.get('image', '-') or '-')}</td>"
                    f"<td>{_esc(d.get('version', '') or '-')}</td>"
                    f"<td class='mono'>{sha}</td>"
                    f"<td>{_esc(d.get('created_at', '-') or '-')}</td>"
                    f"<td>{_esc(d.get('finished_at', '') or '-')}</td>"
                    f"<td>{_esc(d.get('message', '') or '')}</td></tr>"
                )
            table = (
                "<table><thead><tr>"
                "<th>ID</th><th>Status</th><th>Image</th><th>Version</th>"
                "<th>Commit</th><th>Created</th><th>Finished</th><th>Message</th>"
                "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            )
        else:
            table = '<p class="empty">No deployments for this environment.</p>'
        env_panels.append(
            f'<div id="env-{_esc(env)}" class="env-panel" style="display:{display}">{table}</div>'
        )

    # Health check section
    if health_checks:
        hc_rows = []
        for hc in health_checks:
            hc_rows.append(
                f"<tr><td>{_esc(hc['app'])}</td>"
                f"<td>{_esc(hc['environment'])}</td>"
                f"<td>{_health_badge(hc['healthy'])}</td>"
                f"<td>{_esc(hc.get('endpoint', '/health') or '/health')}</td>"
                f"<td>{int(hc.get('attempts', 0))}</td>"
                f"<td>{float(hc.get('elapsed_seconds', 0)):.1f}s</td>"
                f"<td>{_esc(hc.get('checked_at', '-') or '-')}</td>"
                f"<td>{_esc(hc.get('message', '') or '')}</td></tr>"
            )
        health_table = (
            "<table><thead><tr>"
            "<th>App</th><th>Env</th><th>Status</th><th>Endpoint</th>"
            "<th>Attempts</th><th>Elapsed</th><th>Checked At</th><th>Message</th>"
            "</tr></thead><tbody>" + "".join(hc_rows) + "</tbody></table>"
        )
    else:
        health_table = '<p class="empty">No health check records.</p>'

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CloudDeploy Dashboard</title>
  <style>{BASE_CSS}</style>
</head>
<body>
  <div class="container">
    <header>
      <h1>CloudDeploy Dashboard</h1>
      <span id="live-indicator" class="live">&#9679; live</span>
    </header>
    {cards}
    <div class="section">
      <h2>Deployments</h2>
      {env_tabs}
      {"".join(env_panels)}
    </div>
    <div class="section">
      <h2>Health Checks</h2>
      {health_table}
    </div>
  </div>
  {SSE_SCRIPT}
</body>
</html>"""