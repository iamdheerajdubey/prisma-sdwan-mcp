import { api } from "../api.js";
import { showFindingDetail, showSiteDetail } from "../details.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, number, relativeTime, setHeader, severityBar, statusBadge } from "../ui.js";

export async function renderOverview(container, { refresh = false, navigate } = {}) {
  setHeader("Network overview", "Current service health and customer impact");
  container.innerHTML = loadingState();
  const data = await api.dashboard(refresh);
  const summary = data.summary || {};
  document.getElementById("siteNavCount").textContent = summary.sites_total ?? "—";
  document.getElementById("findingNavCount").textContent = summary.active_findings ?? "—";

  container.innerHTML = `
    <div class="page-heading">
      <div><div class="eyebrow">Global network</div><h2>Service health at a glance</h2><p>Live conditions consolidated from the available Prisma SD-WAN MCP capabilities.</p></div>
      <div>${statusBadge(summary.sites_critical > 0 ? "critical" : summary.sites_degraded > 0 ? "degraded" : summary.sites_total ? "healthy" : "unknown")}</div>
    </div>

    <div class="metric-grid">
      ${metricCard("Sites", number(summary.sites_total), "Visible network locations")}
      ${metricCard("Healthy", number(summary.sites_healthy), "Operating normally", "healthy")}
      ${metricCard("Degraded", number(summary.sites_degraded), "Reduced service quality", "degraded")}
      ${metricCard("Critical", number(summary.sites_critical), "Immediate attention", "critical")}
      ${metricCard("Active findings", number(summary.active_findings), `${number(summary.critical_findings, 0)} critical · ${number(summary.high_findings, 0)} high`)}
    </div>

    <div class="dashboard-grid section">
      <section class="panel">
        <div class="panel-header"><div><h3>What needs attention</h3><p>Highest-priority customer-impacting conditions</p></div><button class="text-button" id="viewAllFindings">View all findings</button></div>
        <div id="overviewFindings"></div>
      </section>
      <section class="panel">
        <div class="panel-header"><div><h3>Site health</h3><p>Locations ordered by current risk</p></div><button class="text-button" id="viewAllSites">View all sites</button></div>
        <div id="overviewSites"></div>
      </section>
    </div>

    ${data.data_quality?.complete === false ? `<div class="section info-box"><h4>Limited network data</h4><p>${escapeHtml(data.data_quality.message)} Missing: ${escapeHtml((data.data_quality.missing || []).join(", "))}.</p></div>` : ""}
  `;

  renderFindings(document.getElementById("overviewFindings"), data.attention || []);
  renderSites(document.getElementById("overviewSites"), data.sites || []);
  document.getElementById("viewAllFindings").addEventListener("click", () => navigate("findings"));
  document.getElementById("viewAllSites").addEventListener("click", () => navigate("sites"));
  hydrateIcons(container);
}

function metricCard(label, value, meta, status = "") {
  return `<article class="metric-card ${status ? `status-${status}` : ""}"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(value)}</div><div class="metric-meta">${escapeHtml(meta)}</div></article>`;
}

function renderFindings(target, findings) {
  if (!findings.length) {
    target.innerHTML = emptyState("No active findings", "No customer-impacting monitoring records were returned.");
    return;
  }
  target.innerHTML = `<div class="finding-list">${findings.map((finding, index) => `
    <button class="finding-row" data-index="${index}">
      ${severityBar(finding.severity)}
      <div><div class="row-title">${escapeHtml(finding.title)}</div><div class="row-subtitle">${escapeHtml(finding.site_name)} · ${escapeHtml(finding.impact)}</div></div>
      <div class="row-meta hide-mobile">${escapeHtml(finding.resource)}<br>${relativeTime(finding.started)}</div>
      <span class="row-arrow" data-icon="arrow"></span>
    </button>`).join("")}</div>`;
  target.querySelectorAll("[data-index]").forEach((button) => button.addEventListener("click", () => showFindingDetail(findings[Number(button.dataset.index)])));
}

function renderSites(target, sites) {
  if (!sites.length) {
    target.innerHTML = emptyState("No sites returned", "The available inventory tools did not return recognizable site records.");
    return;
  }
  target.innerHTML = `<div class="site-list">${sites.map((site) => `
    <button class="site-row" data-site-id="${escapeHtml(site.id)}">
      ${severityBar(site.status)}
      <div><div class="row-title">${escapeHtml(site.name)}</div><div class="row-subtitle">${escapeHtml([site.city, site.country].filter(Boolean).join(", ") || "Network site")}</div></div>
      <div class="row-meta hide-tablet">${site.device_count ?? "—"} devices</div>
      <div class="hide-mobile">${statusBadge(site.status)}</div>
      <span class="row-arrow" data-icon="arrow"></span>
    </button>`).join("")}</div>`;
  target.querySelectorAll("[data-site-id]").forEach((button) => button.addEventListener("click", () => showSiteDetail(button.dataset.siteId)));
}
