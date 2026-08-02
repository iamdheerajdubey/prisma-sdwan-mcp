import { api } from "../api.js";
import { showFindingDetail, showResourceDetail, showSiteDetail } from "../details.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, setHeader, statusBadge } from "../ui.js";

const SUGGESTIONS = [
  "Which sites need attention?",
  "Show active network issues",
  "How is Amsterdam Branch?",
  "Show devices and circuits",
  "Is packet loss affecting the network?",
];

export async function renderAsk(container) {
  setHeader("Ask Network", "Ask supported questions using customer and resource names");
  container.innerHTML = `
    <div class="ask-shell">
      <section class="ask-hero">
        <div class="eyebrow">Guided network assistant</div>
        <h2>What do you need to know?</h2>
        <p>Ask about site health, active findings, devices, paths, or performance. The application selects and runs the relevant MCP workflows in the background.</p>
        <div class="ask-input-row"><input class="input" id="askInput" placeholder="Why is Amsterdam internet slow?"><button class="button" id="askButton">Ask network</button></div>
        <div class="ask-suggestions">${SUGGESTIONS.map((text) => `<button class="suggestion" data-question="${escapeHtml(text)}">${escapeHtml(text)}</button>`).join("")}</div>
      </section>
      <div id="askAnswer"></div>
    </div>`;

  async function ask(question) {
    if (!question.trim()) return;
    const target = document.getElementById("askAnswer");
    target.innerHTML = `<div class="answer-card">${loadingState()}</div>`;
    const data = await api.ask(question);
    target.innerHTML = `<div class="answer-card"><p>${escapeHtml(data.answer)}</p><div id="answerItems" class="section"></div></div>`;
    renderAnswerItems(document.getElementById("answerItems"), data);
  }

  document.getElementById("askButton").addEventListener("click", () => ask(document.getElementById("askInput").value));
  document.getElementById("askInput").addEventListener("keydown", (event) => { if (event.key === "Enter") ask(event.target.value); });
  container.querySelectorAll("[data-question]").forEach((button) => button.addEventListener("click", () => {
    document.getElementById("askInput").value = button.dataset.question;
    ask(button.dataset.question);
  }));
  hydrateIcons(container);
}

function renderAnswerItems(target, data) {
  const items = data.items;
  if (!items || (Array.isArray(items) && !items.length)) {
    target.innerHTML = emptyState("No supporting records", "The answer did not return additional network objects.");
    return;
  }
  if (data.type === "findings") {
    target.innerHTML = `<div class="finding-list panel">${items.map((finding, index) => `<button class="finding-row" data-index="${index}"><span class="severity-bar ${escapeHtml(finding.severity)}"></span><div><div class="row-title">${escapeHtml(finding.title)}</div><div class="row-subtitle">${escapeHtml(finding.site_name)} · ${escapeHtml(finding.resource)}</div></div><div class="hide-mobile">${statusBadge(finding.severity)}</div><span data-icon="arrow"></span></button>`).join("")}</div>`;
    target.querySelectorAll("[data-index]").forEach((button) => button.addEventListener("click", () => showFindingDetail(items[Number(button.dataset.index)])));
  } else if (data.type === "site_list") {
    target.innerHTML = `<div class="card-grid">${items.map((site) => `<article class="site-card" data-site-id="${escapeHtml(site.id)}"><div class="card-top"><div><h3 class="card-title">${escapeHtml(site.name)}</h3><div class="card-subtitle">${escapeHtml(site.city || "Network location")}</div></div>${statusBadge(site.status)}</div></article>`).join("")}</div>`;
    target.querySelectorAll("[data-site-id]").forEach((card) => card.addEventListener("click", () => showSiteDetail(card.dataset.siteId)));
  } else if (data.type === "sites") {
    target.innerHTML = `<div class="card-grid">${items.map((detail) => `<article class="site-card" data-site-id="${escapeHtml(detail.site.id)}"><div class="card-top"><div><h3 class="card-title">${escapeHtml(detail.site.name)}</h3><div class="card-subtitle">${detail.summary.active_findings || 0} active findings</div></div>${statusBadge(detail.site.status)}</div></article>`).join("")}</div>`;
    target.querySelectorAll("[data-site-id]").forEach((card) => card.addEventListener("click", () => showSiteDetail(card.dataset.siteId)));
  } else if (data.type === "resources") {
    target.innerHTML = `<div class="card-grid">${items.map((resource, index) => `<article class="resource-card" data-index="${index}"><div class="card-top"><div><h3 class="card-title">${escapeHtml(resource.name)}</h3><div class="card-subtitle">${escapeHtml(resource.type)}</div></div>${statusBadge(resource.status)}</div></article>`).join("")}</div>`;
    target.querySelectorAll("[data-index]").forEach((card) => card.addEventListener("click", () => showResourceDetail(items[Number(card.dataset.index)])));
  } else if (data.type === "telemetry") {
    const summary = items.summary || {};
    target.innerHTML = `<div class="metric-grid">${Object.entries(summary).slice(0, 5).map(([key, value]) => `<article class="metric-card"><div class="metric-label">${escapeHtml(key.replaceAll("_", " "))}</div><div class="metric-value">${escapeHtml(value.current ?? "—")}</div><div class="metric-meta">Average ${escapeHtml(value.average ?? "—")}</div></article>`).join("")}</div>`;
  } else {
    target.innerHTML = emptyState("No structured answer", "Try asking about sites, findings, resources, or telemetry.");
  }
  hydrateIcons(target);
}
