import { api } from "../api.js";
import { showSiteDetail } from "../details.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, setHeader, statusBadge } from "../ui.js";

export async function renderSites(container, { refresh = false } = {}) {
  setHeader("Sites", "Health and service state by network location");
  container.innerHTML = loadingState();
  const data = await api.sites(refresh);
  let items = data.items || [];
  let status = "all";
  let query = "";

  container.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Locations</div><h2>Network sites</h2><p>Select a location to view connectivity, devices, and current findings.</p></div></div>
    <div class="toolbar">
      <div class="search-box"><span data-icon="search"></span><input class="input" id="siteSearch" placeholder="Search by site, city, or country"></div>
      <div class="filter-group" id="siteFilters">
        <button class="filter-chip active" data-status="all">All ${items.length}</button>
        <button class="filter-chip" data-status="healthy">Healthy ${items.filter((item) => item.status === "healthy").length}</button>
        <button class="filter-chip" data-status="degraded">Degraded ${items.filter((item) => item.status === "degraded").length}</button>
        <button class="filter-chip" data-status="critical">Critical ${items.filter((item) => item.status === "critical").length}</button>
      </div>
    </div>
    <div id="siteGrid"></div>`;

  const draw = () => {
    const filtered = items.filter((site) => {
      const matchStatus = status === "all" || site.status === status;
      const text = `${site.name} ${site.city || ""} ${site.country || ""}`.toLowerCase();
      return matchStatus && (!query || text.includes(query));
    });
    const target = document.getElementById("siteGrid");
    if (!filtered.length) {
      target.innerHTML = emptyState("No matching sites", "Change the status filter or search term.");
      return;
    }
    target.innerHTML = `<div class="card-grid">${filtered.map((site) => `
      <article class="site-card" tabindex="0" data-site-id="${escapeHtml(site.id)}">
        <div class="card-top"><div><h3 class="card-title">${escapeHtml(site.name)}</h3><div class="card-subtitle">${escapeHtml([site.city, site.country].filter(Boolean).join(", ") || "Network location")}</div></div>${statusBadge(site.status)}</div>
        <div class="card-facts">
          <div class="card-fact"><span>Devices</span><strong>${site.device_count ?? "Not reported"}</strong></div>
          <div class="card-fact"><span>Findings</span><strong>${site.active_findings ?? "Not reported"}</strong></div>
        </div>
      </article>`).join("")}</div>`;
    target.querySelectorAll("[data-site-id]").forEach((card) => {
      const open = () => showSiteDetail(card.dataset.siteId);
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") open(); });
    });
  };

  document.getElementById("siteSearch").addEventListener("input", (event) => { query = event.target.value.trim().toLowerCase(); draw(); });
  document.getElementById("siteFilters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-status]");
    if (!button) return;
    status = button.dataset.status;
    document.querySelectorAll("#siteFilters .filter-chip").forEach((chip) => chip.classList.toggle("active", chip === button));
    draw();
  });
  hydrateIcons(container);
  draw();
}
