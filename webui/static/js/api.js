const MODE_KEY = "prisma_console_mode";
const LIVE_ONLY_PREFIXES = ["/api/admin", "/api/assistant", "/api/trace"];

export function getMode() {
  return localStorage.getItem(MODE_KEY) || "live";
}

export function setMode(mode) {
  localStorage.setItem(MODE_KEY, mode === "demo" ? "demo" : "live");
}

function route(path) {
  if (getMode() === "demo" && path.startsWith("/api/") && !LIVE_ONLY_PREFIXES.some((prefix) => path.startsWith(prefix))) {
    return path.replace("/api", "/api/demo");
  }
  return path;
}

async function request(path, options = {}, bypassMode = false) {
  const response = await fetch(bypassMode ? path : route(path), {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Invalid server response (${response.status})`);
  }
  if (!response.ok || data?.ok === false) {
    const message = data?.error || `Request failed (${response.status})`;
    const error = new Error(message);
    error.detail = data?.error_detail || null;
    throw error;
  }
  return data;
}

export const api = {
  get(path) { return request(path); },
  post(path, body) { return request(path, { method: "POST", body: JSON.stringify(body || {}) }); },
  status() { return request("/api/status"); },
  liveStatus() { return request("/api/status", {}, true); },
  dashboard(refresh = false) { return request(`/api/dashboard${refresh ? "?refresh=1" : ""}`); },
  sites(refresh = false) { return request(`/api/sites${refresh ? "?refresh=1" : ""}`); },
  site(id, refresh = false) { return request(`/api/sites/${encodeURIComponent(id)}${refresh ? "?refresh=1" : ""}`); },
  findings(siteId = "", refresh = false) {
    const params = new URLSearchParams();
    if (siteId) params.set("site_id", siteId);
    if (refresh) params.set("refresh", "1");
    return request(`/api/findings${params.toString() ? `?${params}` : ""}`);
  },
  resources(kind, query) {
    const params = new URLSearchParams({ kind: kind || "", q: query || "" });
    return request(`/api/resources/search?${params}`);
  },
  telemetry(params = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    });
    return request(`/api/telemetry${query.toString() ? `?${query}` : ""}`);
  },
  tools() { return request("/api/admin/tools"); },
  call(tool, args) { return request("/api/admin/call", { method: "POST", body: JSON.stringify({ tool, args }) }); },
  clearCache() { return request("/api/cache/clear", { method: "POST", body: "{}" }); },
  trace() { return request("/api/trace"); },
  clearTrace() { return request("/api/trace/clear", { method: "POST", body: "{}" }); },
  assistantStatus() { return request("/api/assistant/status"); },
  setAssistantKey(apiKey) { return request("/api/assistant/key", { method: "POST", body: JSON.stringify({ api_key: apiKey }) }); },
  clearAssistantKey() { return request("/api/assistant/key/clear", { method: "POST", body: "{}" }); },
};
