import { api } from "../api.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, setHeader } from "../ui.js";

export async function renderTelemetry(container, { refresh = false } = {}) {
  setHeader("Telemetry", "Recorded link-quality and bandwidth metrics by site");
  container.innerHTML = loadingState();
  const sitesData = await api.sites();
  const sites = sitesData.items || [];
  const selectedSite = localStorage.getItem("prisma_selected_site") || sites[0]?.id || "";

  container.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Performance</div><h2>Network telemetry</h2><p>Recorded telemetry from the last MCP metrics window -- not a live probe.</p></div></div>
    <div class="toolbar">
      <select class="select" id="telemetrySite" style="max-width:310px">${sites.map((site) => `<option value="${escapeHtml(site.id)}" ${site.id === selectedSite ? "selected" : ""}>${escapeHtml(site.name)}</option>`).join("")}</select>
      <select class="select" id="telemetryRange" style="max-width:180px"><option value="1">Last hour</option><option value="6" selected>Last 6 hours</option><option value="24">Last 24 hours</option></select>
      <button class="button" id="loadTelemetry">Load telemetry</button>
    </div>
    <div id="telemetryContent"></div>`;

  async function load(force = false) {
    const siteId = document.getElementById("telemetrySite").value;
    const hours = Number(document.getElementById("telemetryRange").value || 6);
    if (siteId) localStorage.setItem("prisma_selected_site", siteId);
    const target = document.getElementById("telemetryContent");
    if (!siteId) {
      target.innerHTML = emptyState("No site selected", "Telemetry is read per site.");
      return;
    }
    target.innerHTML = loadingState();
    const data = await api.telemetry({ site_id: siteId, hours, refresh: force ? "1" : "" });
    const bandwidth = data.bandwidth || [];
    const linkQuality = data.link_quality || [];
    if (!bandwidth.length && !linkQuality.length) {
      target.innerHTML = emptyState("No telemetry returned", "This site may have no active WAN paths in the current window.");
      return;
    }
    target.innerHTML = `
      ${data.snapshot_time ? `<p class="help-text">Snapshot time: ${escapeHtml(data.snapshot_time)}</p>` : ""}
      <div class="dashboard-grid section">
        <section class="panel"><div class="panel-header"><div><h3>Bandwidth</h3><p>Per-series recorded bandwidth usage</p></div></div>${seriesTable(bandwidth)}</section>
        <section class="panel"><div class="panel-header"><div><h3>Link quality</h3><p>Latency, loss, jitter, and MOS per path</p></div></div>${pathTable(linkQuality)}</section>
      </div>`;
  }

  document.getElementById("loadTelemetry").addEventListener("click", () => load(true));
  document.getElementById("telemetrySite").addEventListener("change", () => load(false));
  hydrateIcons(container);
  await load(refresh);
}

function seriesTable(series) {
  if (!series.length) return '<div class="info-box"><h4>No bandwidth series</h4><p>Nothing was returned for this window.</p></div>';
  return `<div class="panel table-wrap"><table class="data-table"><thead><tr><th>Metric</th><th>Path / WAN interface</th><th>Datapoints</th></tr></thead><tbody>${series.map((entry) => `
    <tr><td>${escapeHtml(entry.metric || "—")}</td><td>${escapeHtml(entry.path_id || entry.wan_interface_id || entry.waninterface_id || "—")}</td><td>${(entry.datapoints || []).length}</td></tr>`).join("")}</tbody></table></div>`;
}

function pathTable(paths) {
  if (!paths.length) return '<div class="info-box"><h4>No link-quality data</h4><p>Nothing was returned for this window.</p></div>';
  const metricKeys = Array.from(new Set(paths.flatMap((path) => Object.keys(path)).filter((key) => key !== "path_id" && key !== "remote_site_id")));
  return `<div class="panel table-wrap"><table class="data-table"><thead><tr><th>Path</th>${metricKeys.map((key) => `<th>${escapeHtml(key)}</th>`).join("")}</tr></thead><tbody>${paths.map((path) => `
    <tr><td>${escapeHtml(path.path_id ?? "—")}</td>${metricKeys.map((key) => `<td>${path[key] ? "present" : "—"}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
