import { api } from "./api.js";
import { escapeHtml, hydrateIcons, openModal, relativeTime, severityBar, statusBadge, toast } from "./ui.js";

function setModal(eyebrow, title, body) {
  document.getElementById("detailModalEyebrow").textContent = eyebrow;
  document.getElementById("detailModalTitle").textContent = title;
  const target = document.getElementById("detailModalBody");
  target.innerHTML = body;
  hydrateIcons(target);
  openModal("detailModal");
}

export async function showSiteDetail(siteId) {
  setModal("Site", "Loading site", '<div class="skeleton" style="height:420px"></div>');
  try {
    const data = await api.site(siteId);
    const site = data.site;
    const summary = data.summary || {};
    setModal("Site", site.name, `
      <div class="detail-hero">
        <div><h3>${escapeHtml(site.name)}</h3><p>${escapeHtml([site.city, site.country].filter(Boolean).join(", ") || "Network location")}</p></div>
        ${statusBadge(site.status)}
      </div>
      <div class="detail-summary">
        <div class="detail-stat"><span>Devices</span><strong>${summary.devices_total ?? 0}</strong></div>
        <div class="detail-stat"><span>Healthy devices</span><strong>${summary.devices_healthy ?? 0}</strong></div>
        <div class="detail-stat"><span>Connectivity</span><strong>${summary.connectivity_total ?? 0}</strong></div>
        <div class="detail-stat"><span>Active findings</span><strong>${summary.active_findings ?? 0}</strong></div>
      </div>
      <section class="section">
        <div class="section-header"><div><h3>Current findings</h3><p>Customer-impacting conditions associated with this site</p></div></div>
        ${data.findings?.length ? `<div class="panel"><div class="finding-list">${data.findings.map((finding) => `
          <div class="finding-row">
            ${severityBar(finding.severity)}
            <div><div class="row-title">${escapeHtml(finding.title)}</div><div class="row-subtitle">${escapeHtml(finding.impact)}</div></div>
            <div class="row-meta hide-mobile">${escapeHtml(finding.resource)}<br>${relativeTime(finding.started)}</div>
            ${statusBadge(finding.severity)}
          </div>`).join("")}</div></div>` : '<div class="info-box"><h4>No active findings</h4><p>No site-specific alarms were returned by the available MCP workflows.</p></div>'}
      </section>
      <section class="section">
        <div class="section-header"><div><h3>Connectivity</h3><p>Circuits, paths, links, and interfaces visible for this site</p></div></div>
        ${resourceTable(data.connectivity || [])}
      </section>
      <section class="section">
        <div class="section-header"><div><h3>Devices</h3><p>Managed network devices at this location</p></div></div>
        ${resourceTable(data.devices || [])}
      </section>
    `);
  } catch (error) {
    toast(error.message, "error");
    setModal("Site", "Unable to load site", `<div class="info-box"><h4>Site details unavailable</h4><p>${escapeHtml(error.message)}</p></div>`);
  }
}

function resourceTable(items) {
  if (!items.length) return '<div class="info-box"><h4>No data returned</h4><p>No compatible resource records were available for this section.</p></div>';
  return `<div class="panel table-wrap"><table class="data-table"><thead><tr><th>Resource</th><th>Type</th><th>Status</th><th>Model</th></tr></thead><tbody>${items.map((item) => `<tr><td><strong>${escapeHtml(item.name)}</strong></td><td>${escapeHtml(item.type)}</td><td>${statusBadge(item.status)}</td><td>${escapeHtml(item.model || "—")}</td></tr>`).join("")}</tbody></table></div>`;
}

export function showFindingDetail(finding) {
  setModal("Finding", finding.title, `
    <div class="detail-hero">
      <div><h3>${escapeHtml(finding.title)}</h3><p>${escapeHtml(finding.site_name)} · ${escapeHtml(finding.resource)}</p></div>
      ${statusBadge(finding.severity)}
    </div>
    <div class="finding-detail-grid section">
      <div class="info-box"><h4>Customer impact</h4><p>${escapeHtml(finding.impact || "No confirmed customer impact is available from the current evidence.")}</p></div>
      <div class="info-box"><h4>Observed</h4><p>Started ${relativeTime(finding.started)}. Current state: ${escapeHtml(finding.status || "active")}.</p></div>
      <div class="info-box"><h4>Recommended next step</h4><p>${escapeHtml(finding.recommendation || "Review the affected resource and supporting telemetry.")}</p></div>
      <div class="info-box"><h4>Affected resource</h4><p>${escapeHtml(finding.resource || "Network resource")} at ${escapeHtml(finding.site_name || "Unknown site")}.</p></div>
    </div>
    ${finding.raw ? `<section class="section"><details><summary class="text-button">Technical evidence</summary><pre class="code-block">${escapeHtml(JSON.stringify(finding.raw, null, 2))}</pre></details></section>` : ""}
  `);
}

export function showResourceDetail(resource) {
  setModal(resource.type || "Resource", resource.name, `
    <div class="detail-hero">
      <div><h3>${escapeHtml(resource.name)}</h3><p>${escapeHtml(resource.site_name || resource.description || "Network resource")}</p></div>
      ${statusBadge(resource.status)}
    </div>
    <div class="detail-summary">
      <div class="detail-stat"><span>Type</span><strong>${escapeHtml(resource.type || "Resource")}</strong></div>
      <div class="detail-stat"><span>Site</span><strong>${escapeHtml(resource.site_name || "—")}</strong></div>
      <div class="detail-stat"><span>Model</span><strong>${escapeHtml(resource.model || "—")}</strong></div>
      <div class="detail-stat"><span>Status</span><strong>${escapeHtml(resource.status || "unknown")}</strong></div>
    </div>
    ${resource.description ? `<div class="info-box section"><h4>Description</h4><p>${escapeHtml(resource.description)}</p></div>` : ""}
    ${resource.raw ? `<section class="section"><details><summary class="text-button">Technical evidence</summary><pre class="code-block">${escapeHtml(JSON.stringify(resource.raw, null, 2))}</pre></details></section>` : ""}
  `);
}
