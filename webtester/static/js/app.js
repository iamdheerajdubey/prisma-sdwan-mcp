import { api, getMode, setMode } from "./api.js";
import { closeModal, hydrateIcons, openModal, toast } from "./ui.js";
import { renderOverview } from "./pages/overview.js";
import { renderSites } from "./pages/sites.js";
import { renderFindings } from "./pages/findings.js";
import { renderTelemetry } from "./pages/telemetry.js";
import { renderResources } from "./pages/resources.js";
import { renderAsk } from "./pages/ask.js";
import { renderAdmin } from "./pages/admin.js";

const content = document.getElementById("appContent");
if (new URLSearchParams(location.search).get("preview") === "1") setMode("demo");
let currentPage = location.hash.replace("#", "") || "overview";
let renderToken = 0;

const pages = {
  overview: renderOverview,
  sites: renderSites,
  findings: renderFindings,
  telemetry: renderTelemetry,
  resources: renderResources,
  ask: renderAsk,
};

function navigate(page, { refresh = false } = {}) {
  if (!pages[page]) page = "overview";
  currentPage = page;
  if (location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  document.querySelectorAll("[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === page));
  renderCurrent(refresh);
}

async function renderCurrent(refresh = false) {
  const token = ++renderToken;
  try {
    await pages[currentPage](content, { refresh, navigate });
  } catch (error) {
    if (token !== renderToken) return;
    content.innerHTML = `<div class="empty-state"><div class="empty-state-inner"><div class="empty-icon">!</div><h3>Unable to load this view</h3><p>${escapeForText(error.message)}</p><button class="button" id="retryPage">Retry</button></div></div>`;
    document.getElementById("retryPage")?.addEventListener("click", () => renderCurrent(true));
    toast(error.message, "error");
  }
}

async function updateStatus() {
  const mode = getMode();
  document.querySelectorAll("[data-mode]").forEach((button) => button.classList.toggle("active", button.dataset.mode === mode));
  const dot = document.getElementById("sidebarStatusDot");
  const title = document.getElementById("sidebarStatusTitle");
  const meta = document.getElementById("sidebarStatusMeta");
  const banner = document.getElementById("connectionBanner");
  try {
    const status = await api.status();
    dot.className = `status-dot ${status.connected ? "healthy" : "critical"}`;
    title.textContent = mode === "demo" ? "Preview environment" : status.connected ? "Live network connected" : "Live data disconnected";
    meta.textContent = status.controller || status.tenant || "Local customer portal";
    banner.hidden = mode === "demo" || status.connected;
  } catch (error) {
    dot.className = "status-dot critical";
    title.textContent = "Server unavailable";
    meta.textContent = error.message;
    banner.hidden = false;
  }
}

function escapeForText(value) {
  return String(value ?? "").replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char]));
}

document.getElementById("primaryNav").addEventListener("click", (event) => {
  const button = event.target.closest("[data-page]");
  if (button) navigate(button.dataset.page);
});

document.getElementById("refreshButton").addEventListener("click", async () => {
  const button = document.getElementById("refreshButton");
  button.disabled = true;
  try {
    if (getMode() === "live") await api.clearCache();
    await renderCurrent(true);
    await updateStatus();
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", async () => {
  setMode(button.dataset.mode);
  await updateStatus();
  navigate(currentPage, { refresh: true });
}));

function openAdmin() {
  openModal("adminModal");
  renderAdmin("connection");
}

document.getElementById("openAdminButton").addEventListener("click", openAdmin);
document.getElementById("bannerAdminButton").addEventListener("click", openAdmin);
document.querySelectorAll("[data-admin-tab]").forEach((button) => button.addEventListener("click", () => renderAdmin(button.dataset.adminTab)));

document.querySelectorAll("[data-close-modal]").forEach((button) => button.addEventListener("click", () => closeModal(button.dataset.closeModal)));
document.querySelectorAll(".modal-backdrop").forEach((backdrop) => backdrop.addEventListener("click", (event) => { if (event.target === backdrop) closeModal(backdrop.id); }));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") document.querySelectorAll(".modal-backdrop:not([hidden])").forEach((modal) => closeModal(modal.id));
});
document.addEventListener("portal:connection-changed", async () => {
  await updateStatus();
  document.querySelectorAll("[data-mode]").forEach((button) => button.classList.toggle("active", button.dataset.mode === getMode()));
  navigate(currentPage, { refresh: true });
});
window.addEventListener("hashchange", () => navigate(location.hash.replace("#", "") || "overview"));

hydrateIcons();
updateStatus();
navigate(currentPage);
