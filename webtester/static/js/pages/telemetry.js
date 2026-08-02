import { api } from "../api.js";
import { emptyState, escapeHtml, formatMetric, hydrateIcons, loadingState, renderLineChart, setHeader } from "../ui.js";

const METRICS = [
  ["latency_ms", "Latency", "ms"],
  ["packet_loss_pct", "Packet loss", "%"],
  ["jitter_ms", "Jitter", "ms"],
  ["utilization_pct", "Utilization", "%"],
];

export async function renderTelemetry(container, { refresh = false } = {}) {
  setHeader("Telemetry", "Path quality and service performance over time");
  container.innerHTML = loadingState();
  const sitesData = await api.sites();
  const sites = sitesData.items || [];
  const selectedSite = localStorage.getItem("prisma_selected_site") || sites[0]?.id || "";

  container.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Performance</div><h2>Network telemetry</h2><p>Review latency, packet loss, jitter, and utilization without handling API parameters.</p></div></div>
    <div class="toolbar">
      <select class="select" id="telemetrySite" style="max-width:310px"><option value="">All available telemetry</option>${sites.map((site) => `<option value="${escapeHtml(site.id)}" ${site.id === selectedSite ? "selected" : ""}>${escapeHtml(site.name)}</option>`).join("")}</select>
      <select class="select" id="telemetryRange" style="max-width:180px"><option value="1">Last hour</option><option value="6" selected>Last 6 hours</option><option value="24">Last 24 hours</option></select>
      <button class="button" id="loadTelemetry">Load telemetry</button>
    </div>
    <div id="telemetryContent"></div>`;

  async function load(force = false) {
    const siteId = document.getElementById("telemetrySite").value;
    const hours = Number(document.getElementById("telemetryRange").value || 6);
    if (siteId) localStorage.setItem("prisma_selected_site", siteId);
    const end = new Date();
    const start = new Date(end.getTime() - hours * 3600 * 1000);
    const target = document.getElementById("telemetryContent");
    target.innerHTML = loadingState();
    const data = await api.telemetry({ site_id: siteId, start_time: start.toISOString(), end_time: end.toISOString(), refresh: force ? "1" : "" });
    const points = data.points || [];
    const summary = data.summary || {};
    if (!points.length && !Object.keys(summary).length) {
      target.innerHTML = emptyState("No telemetry returned", "Select a site or verify that the discovered monitoring tools support time-series metrics.");
      return;
    }
    target.innerHTML = `<div class="chart-grid">${METRICS.map(([key, title, unit]) => chartCard(title, key, unit, summary[key], points)).join("")}</div>`;
  }

  document.getElementById("loadTelemetry").addEventListener("click", () => load(true));
  document.getElementById("telemetrySite").addEventListener("change", () => load(false));
  hydrateIcons(container);
  await load(refresh);
}

function chartCard(title, key, unit, summary, points) {
  return `<article class="chart-card">
    <div class="chart-title"><div><h3>${escapeHtml(title)}</h3><div class="chart-meta">Average ${formatMetric(summary?.average, unit)} · Maximum ${formatMetric(summary?.maximum, unit)}</div></div><div class="chart-value">${formatMetric(summary?.current, unit)}</div></div>
    ${renderLineChart(points, key)}
  </article>`;
}
