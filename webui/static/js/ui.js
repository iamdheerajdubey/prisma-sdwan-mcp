const ICONS = {
  overview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>',
  sites: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 21s6-5.1 6-11A6 6 0 1 0 6 10c0 5.9 6 11 6 11Z"/><circle cx="12" cy="10" r="2"/></svg>',
  findings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 2.8 19h18.4L12 3Z"/><path d="M12 8v5"/><circle cx="12" cy="16.3" r=".8" fill="currentColor" stroke="none"/></svg>',
  telemetry: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 17h3l3-7 4 10 3-8 2 5h3"/><path d="M3 4v16h18"/></svg>',
  resources: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/></svg>',
  ask: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 5h14v11H9l-4 4V5Z"/><path d="M9 9h6M9 12h4"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.1A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.1A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.1A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.37.3.58.76.6 1.2v1.6c-.02.44-.23.9-.6 1.2Z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 6v5h-5"/><path d="M4 18v-5h5"/><path d="M18.5 9A7 7 0 0 0 6.3 6.3L4 11M5.5 15A7 7 0 0 0 17.7 17.7L20 13"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m6 6 12 12M18 6 6 18"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m9 18 6-6-6-6"/></svg>',
  empty: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5h16v14H4z"/><path d="M8 9h8M8 13h5"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m5 12 4 4L19 6"/></svg>',
  network: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M10.7 7.1 6.3 15.9M13.3 7.1l4.4 8.8M7.5 18h9"/></svg>',
  device: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="4" width="16" height="10" rx="1.5"/><path d="M8 18h8M12 14v4"/></svg>',
  trace: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 12h4l2-7 4 14 2-7h4"/></svg>',
};

export function icon(name) { return ICONS[name] || ICONS.empty; }

export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = icon(node.dataset.icon);
  });
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

export function statusBadge(status) {
  const safe = String(status || "unknown").toLowerCase();
  return `<span class="status-badge ${escapeHtml(safe)}">${escapeHtml(safe)}</span>`;
}

export function severityBar(severity) {
  const safe = String(severity || "unknown").toLowerCase();
  return `<span class="severity-bar ${escapeHtml(safe)}"></span>`;
}

export function relativeTime(value) {
  if (!value) return "Recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} hr ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

export function number(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : new Intl.NumberFormat().format(value);
}

export function emptyState(title, message, action = "") {
  return `<div class="empty-state"><div class="empty-state-inner"><div class="empty-icon">${icon("empty")}</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(message)}</p>${action}</div></div>`;
}

export function loadingState() {
  return `<div class="loading-grid"><div class="skeleton" style="height:118px"></div><div class="skeleton" style="height:220px"></div><div class="skeleton" style="height:180px"></div></div>`;
}

export function setHeader(title, subtitle) {
  document.getElementById("pageTitle").textContent = title;
  document.getElementById("pageSubtitle").textContent = subtitle;
}

export function openModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.hidden = false;
  document.body.style.overflow = "hidden";
  modal.querySelector("button, input, select, textarea")?.focus();
}

export function closeModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.hidden = true;
  if (![...document.querySelectorAll(".modal-backdrop")].some((item) => !item.hidden)) document.body.style.overflow = "";
}

export function toast(message, type = "") {
  const region = document.getElementById("toastRegion");
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  region.appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

export function renderLineChart(points, metric) {
  const values = points.map((point) => Number(point[metric])).filter(Number.isFinite);
  if (values.length < 2) return `<div class="chart-empty">No time-series data returned</div>`;
  const width = 640;
  const height = 176;
  const pad = 12;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const coords = values.map((value, index) => {
    const x = pad + (index / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - ((value - min) / span) * (height - pad * 2);
    return [x, y];
  });
  const line = coords.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${coords.at(-1)[0].toFixed(1)},${height - pad} L${coords[0][0].toFixed(1)},${height - pad} Z`;
  const grid = [0.25, 0.5, 0.75].map((ratio) => `<line class="chart-gridline" x1="${pad}" y1="${height * ratio}" x2="${width - pad}" y2="${height * ratio}"/>`).join("");
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${grid}<path class="chart-area" d="${area}"/><path class="chart-line" d="${line}"/></svg>`;
}

export function formatMetric(value, unit = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const numeric = Number(value);
  const formatted = Math.abs(numeric) >= 100 ? Math.round(numeric) : numeric.toFixed(1).replace(/\.0$/, "");
  return `${formatted}${unit}`;
}
