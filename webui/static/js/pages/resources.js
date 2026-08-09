import { api } from "../api.js";
import { showResourceDetail } from "../details.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, setHeader, statusBadge } from "../ui.js";

const KINDS = [
  ["machine", "Machine"],
  ["application", "Application"],
  ["security_zone", "Security zone"],
  ["wan_network", "WAN network"],
  ["path_group", "Path group"],
  ["service_label", "Service label"],
  ["vrf", "VRF"],
  ["policy", "Policy (any family)"],
];

export async function renderResources(container) {
  setHeader("Resources", "Resolve a machine, application, zone, WAN network, path group, service label, VRF, or policy by name");
  container.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Inventory</div><h2>Find a network resource</h2><p>Choose the kind of object, then search by the name it is known by -- this calls <code>find_resource</code> directly, never a guess across tool types.</p></div></div>
    <div class="toolbar">
      <select class="select" id="resourceKind" style="max-width:220px">${KINDS.map(([value, label]) => `<option value="${value}">${escapeHtml(label)}</option>`).join("")}</select>
      <div class="search-box"><span data-icon="search"></span><input class="input" id="resourceSearch" placeholder="ISP-1, branch-office-zone..."></div>
      <button class="button" id="resourceSearchButton">Search</button>
    </div>
    <div id="resourceResults"></div>`;
  hydrateIcons(container);

  async function search() {
    const kind = document.getElementById("resourceKind").value;
    const query = document.getElementById("resourceSearch").value.trim();
    const target = document.getElementById("resourceResults");
    if (!query) {
      target.innerHTML = emptyState("Enter a name", "Search requires a name or ID to resolve.");
      return;
    }
    target.innerHTML = loadingState();
    const data = await api.resources(kind, query);
    const items = data.items || [];
    if (!items.length) {
      target.innerHTML = emptyState("No matching resources", "Try a broader or exact name for this kind.");
      return;
    }
    target.innerHTML = `<div class="card-grid">${items.map((resource, index) => `
      <article class="resource-card" tabindex="0" data-index="${index}">
        <div class="card-top"><div><h3 class="card-title">${escapeHtml(resource.name)}</h3><div class="card-subtitle">${escapeHtml(resource.type || "Resource")}</div></div>${statusBadge(resource.status)}</div>
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
}
