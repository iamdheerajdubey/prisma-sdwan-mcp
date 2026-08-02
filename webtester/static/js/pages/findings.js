import { api } from "../api.js";
import { showFindingDetail } from "../details.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, relativeTime, setHeader, severityBar, statusBadge } from "../ui.js";

export async function renderFindings(container, { refresh = false } = {}) {
  setHeader("Findings", "Customer-impacting network conditions and recommended next actions");
  container.innerHTML = loadingState();
  const data = await api.findings("", refresh);
  const items = data.items || [];
  let severity = "all";
  let query = "";

  container.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Operations</div><h2>Network findings</h2><p>Prioritized conditions derived from alarms, incidents, and monitoring evidence.</p></div></div>
    <div class="toolbar">
      <div class="search-box"><span data-icon="search"></span><input class="input" id="findingSearch" placeholder="Search by issue, site, or resource"></div>
      <div class="filter-group" id="findingFilters">
        <button class="filter-chip active" data-severity="all">All ${items.length}</button>
        <button class="filter-chip" data-severity="critical">Critical ${items.filter((item) => item.severity === "critical").length}</button>
        <button class="filter-chip" data-severity="high">High ${items.filter((item) => item.severity === "high").length}</button>
        <button class="filter-chip" data-severity="medium">Medium ${items.filter((item) => item.severity === "medium").length}</button>
      </div>
    </div>
    <div class="panel" id="findingsPanel"></div>`;

  const draw = () => {
    const filtered = items.filter((finding) => {
      const matchesSeverity = severity === "all" || finding.severity === severity;
      const text = `${finding.title} ${finding.site_name} ${finding.resource} ${finding.impact}`.toLowerCase();
      return matchesSeverity && (!query || text.includes(query));
    });
    const panel = document.getElementById("findingsPanel");
    if (!filtered.length) {
      panel.innerHTML = emptyState("No matching findings", items.length ? "Change the filter or search term." : "No active monitoring records were returned.");
      return;
    }
    panel.innerHTML = `<div class="finding-list">${filtered.map((finding, index) => `
      <button class="finding-row" data-index="${index}">
        ${severityBar(finding.severity)}
        <div><div class="row-title">${escapeHtml(finding.title)}</div><div class="row-subtitle">${escapeHtml(finding.impact)}</div></div>
        <div class="row-meta hide-mobile">${escapeHtml(finding.site_name)}<br>${escapeHtml(finding.resource)} · ${relativeTime(finding.started)}</div>
        ${statusBadge(finding.severity)}
      </button>`).join("")}</div>`;
    panel.querySelectorAll("[data-index]").forEach((button) => button.addEventListener("click", () => showFindingDetail(filtered[Number(button.dataset.index)])));
  };

  document.getElementById("findingSearch").addEventListener("input", (event) => { query = event.target.value.trim().toLowerCase(); draw(); });
  document.getElementById("findingFilters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-severity]");
    if (!button) return;
    severity = button.dataset.severity;
    document.querySelectorAll("#findingFilters .filter-chip").forEach((chip) => chip.classList.toggle("active", chip === button));
    draw();
  });
  hydrateIcons(container);
  draw();
}
