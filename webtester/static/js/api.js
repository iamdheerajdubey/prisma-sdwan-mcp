const MODE_KEY = "prisma_network_experience_mode";

export function getMode() {
  return localStorage.getItem(MODE_KEY) || "live";
}

export function setMode(mode) {
  localStorage.setItem(MODE_KEY, mode === "demo" ? "demo" : "live");
}

function route(path) {
  if (getMode() === "demo" && path.startsWith("/api/") && !path.startsWith("/api/admin") && path !== "/api/connect" && path !== "/api/capabilities") {
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
    throw new Error(data?.error || `Request failed (${response.status})`);
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
  resources(query = "") { return request(`/api/resources/search?q=${encodeURIComponent(query)}`); },
  telemetry(params = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    });
    return request(`/api/telemetry${query.toString() ? `?${query}` : ""}`);
  },
  ask(question) { return request("/api/ask", { method: "POST", body: JSON.stringify({ question }) }); },
  connect(credentials) { return request("/api/connect", { method: "POST", body: JSON.stringify(credentials) }); },
  capabilities() { return request("/api/capabilities"); },
  tools() { return request("/api/admin/tools"); },
  call(tool, args) { return request("/api/admin/call", { method: "POST", body: JSON.stringify({ tool, args }) }); },
  clearCache() { return request("/api/cache/clear", { method: "POST", body: "{}" }); },
};
