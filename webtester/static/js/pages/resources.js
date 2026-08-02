import { api } from "../api.js";
import { showResourceDetail } from "../details.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, setHeader, statusBadge } from "../ui.js";

export async function renderResources(container) {
  setHeader("Resources", "Search sites, devices, circuits, paths, interfaces, and peers");
  container.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Inventory</div><h2>Find a network resource</h2><p>Search by the name customers and operators already use. Technical identifiers remain hidden.</p></div></div>
    <div class="toolbar"><div class="search-box"><span data-icon="search"></span><input class="input" id="resourceSearch" placeholder="Search Amsterdam, ISP-1, branch device..."></div><button class="button" id="resourceSearchButton">Search</button></div>
    <div id="resourceResults"></div>`;
  hydrateIcons(container);

  async function search() {
    const query = document.getElementById("resourceSearch").value.trim();
    const target = document.getElementById("resourceResults");
    target.innerHTML = loadingState();
    const data = await api.resources(query);
    const items = data.items || [];
    if (!items.length) {
      target.innerHTML = emptyState("No matching resources", query ? "Try a broader name or site search." : "No recognizable inventory resources were returned.");
      return;
    }
    target.innerHTML = `<div class="card-grid">${items.map((resource, index) => `
      <article class="resource-card" tabindex="0" data-index="${index}">
        <div class="card-top"><div><h3 class="card-title">${escapeHtml(resource.name)}</h3><div class="card-subtitle">${escapeHtml(resource.type || "Network resource")}</div></div>${statusBadge(resource.status)}</div>
        <div class="card-facts"><div class="card-fact"><span>Site</span><strong>${escapeHtml(resource.site_name || "Not assigned")}</strong></div><div class="card-fact"><span>Model</span><strong>${escapeHtml(resource.model || "Not reported")}</strong></div></div>
      </article>`).join("")}</div>`;
    target.querySelectorAll("[data-index]").forEach((card) => {
      const open = () => showResourceDetail(items[Number(card.dataset.index)]);
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") open(); });
    });
  }

  document.getElementById("resourceSearchButton").addEventListener("click", search);
  document.getElementById("resourceSearch").addEventListener("keydown", (event) => { if (event.key === "Enter") search(); });
  await search();
}
