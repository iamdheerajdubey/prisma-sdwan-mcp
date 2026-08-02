import { api, getMode, setMode } from "../api.js";
import { escapeHtml, hydrateIcons, toast } from "../ui.js";

let activeTab = "connection";
let cachedTools = null;

export async function renderAdmin(tab = activeTab) {
  activeTab = tab;
  document.querySelectorAll("[data-admin-tab]").forEach((button) => button.classList.toggle("active", button.dataset.adminTab === tab));
  const target = document.getElementById("adminContent");
  target.innerHTML = '<div class="skeleton" style="height:420px"></div>';
  if (tab === "connection") return renderConnection(target);
  if (tab === "capabilities") return renderCapabilities(target);
  return renderTools(target);
}

async function renderConnection(target) {
  let status;
  try { status = await api.liveStatus(); } catch (error) { status = { connected: false, error: error.message }; }
  target.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Data source</div><h2>Prisma connection</h2><p>Customer users do not see or manage these credentials.</p></div></div>
    <div class="info-box"><h4>Current state</h4><p>${status.connected ? `Connected to ${escapeHtml(status.controller || "Prisma SD-WAN")}. Tenant ${escapeHtml(status.tenant || "configured")}.` : "No live Prisma session is active."}</p></div>
    <form id="connectionForm" class="section">
      <div class="form-grid">
        <div class="form-field full"><label for="adminClientId">Service account client ID</label><input class="input" id="adminClientId" autocomplete="off" placeholder="name@tsg.iam.panserviceaccount.com"></div>
        <div class="form-field full"><label for="adminClientSecret">Service account secret</label><input class="input" type="password" id="adminClientSecret" autocomplete="new-password" placeholder="Secret is sent only to this local server"></div>
        <div class="form-field"><label for="adminTsgId">Tenant service group ID</label><input class="input" id="adminTsgId" autocomplete="off" placeholder="1234567890"></div>
        <div class="form-field"><label for="adminRegion">Region (optional)</label><input class="input" id="adminRegion" autocomplete="off" placeholder="europe"></div>
      </div>
      <div class="form-actions"><button class="button" type="submit">Connect live data</button><button class="button button-secondary" type="button" id="usePreviewButton">Use preview mode</button></div>
      <p class="help-text">For normal operation, configure PAN_CLIENT_ID, PAN_CLIENT_SECRET, PAN_TSG_ID, and optionally PAN_REGION as environment variables before starting the server.</p>
    </form>`;
  target.querySelector("#connectionForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      await api.connect({
        client_id: document.getElementById("adminClientId").value.trim(),
        client_secret: document.getElementById("adminClientSecret").value,
        tsg_id: document.getElementById("adminTsgId").value.trim(),
        region: document.getElementById("adminRegion").value.trim(),
      });
      setMode("live");
      toast("Live Prisma SD-WAN connection established.", "success");
      document.dispatchEvent(new CustomEvent("portal:connection-changed"));
      renderConnection(target);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById("usePreviewButton").addEventListener("click", () => {
    setMode("demo");
    toast("Preview mode enabled.", "success");
    document.dispatchEvent(new CustomEvent("portal:connection-changed"));
  });
}

async function renderCapabilities(target) {
  try {
    const data = await api.capabilities();
    const intents = data.intents || {};
    target.innerHTML = `
      <div class="page-heading"><div><div class="eyebrow">Application mapping</div><h2>Detected capabilities</h2><p>The application maps ${data.tool_count || 0} discovered MCP tools into customer workflows.</p></div></div>
      <div class="panel table-wrap"><table class="data-table"><thead><tr><th>Customer workflow</th><th>Available</th><th>Candidate tools</th><th>Best match</th></tr></thead><tbody>${Object.entries(intents).map(([name, item]) => `<tr><td><strong>${escapeHtml(name)}</strong></td><td>${item.available ? '<span class="status-badge healthy">available</span>' : '<span class="status-badge unknown">unavailable</span>'}</td><td>${item.candidate_count || 0}</td><td><code>${escapeHtml(item.best_match || "—")}</code></td></tr>`).join("")}</tbody></table></div>
      <div class="info-box section"><h4>Interpretation</h4><p>Availability means a discovered MCP tool matched the workflow by name, description, category, and required parameters. Real response compatibility is confirmed only when live data is loaded.</p></div>`;
  } catch (error) {
    target.innerHTML = `<div class="info-box"><h4>Capabilities unavailable</h4><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function renderTools(target) {
  try {
    cachedTools ||= (await api.tools()).tools || [];
    target.innerHTML = `
      <div class="page-heading"><div><div class="eyebrow">Engineering</div><h2>MCP tool explorer</h2><p>Raw tool access is isolated here for validation and troubleshooting.</p></div></div>
      <div class="toolbar"><div class="search-box"><span data-icon="search"></span><input class="input" id="toolSearch" placeholder="Filter tools"></div></div>
      <div class="tool-explorer" id="toolList"></div>`;
    hydrateIcons(target);
    const draw = () => {
      const query = document.getElementById("toolSearch").value.trim().toLowerCase();
      const tools = cachedTools.filter((tool) => !query || `${tool.name} ${tool.description} ${tool.category}`.toLowerCase().includes(query));
      document.getElementById("toolList").innerHTML = tools.map((tool, index) => toolCard(tool, index)).join("") || '<div class="info-box"><h4>No matching tools</h4><p>Change the filter.</p></div>';
      bindToolActions(tools);
    };
    document.getElementById("toolSearch").addEventListener("input", draw);
    draw();
  } catch (error) {
    target.innerHTML = `<div class="info-box"><h4>Tool explorer unavailable</h4><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function toolCard(tool, index) {
  const properties = tool.parameters?.properties || {};
  const required = new Set(tool.parameters?.required || []);
  return `<details class="tool-card"><summary><div class="tool-name">${escapeHtml(tool.name)}</div><div class="tool-description">${escapeHtml(tool.description || tool.category)}</div></summary><div class="tool-body"><div class="form-grid">${Object.entries(properties).map(([name, schema]) => inputFor(tool.name, name, schema, required.has(name))).join("") || '<div class="help-text">No arguments.</div>'}</div><div class="form-actions"><button class="button" data-run-tool="${escapeHtml(tool.name)}">Run tool</button></div><div data-tool-result="${escapeHtml(tool.name)}"></div></div></details>`;
}

function inputFor(toolName, name, schema, required) {
  const id = `tool_${toolName}_${name}`.replace(/[^a-zA-Z0-9_]/g, "_");
  const type = schema.type || "string";
  if (type === "boolean") return `<div class="form-field"><label><input type="checkbox" id="${id}" data-tool-input="${escapeHtml(toolName)}" data-arg="${escapeHtml(name)}" data-type="boolean"> ${escapeHtml(name)}${required ? " *" : ""}</label></div>`;
  if (type === "object" || type === "array") return `<div class="form-field full"><label for="${id}">${escapeHtml(name)}${required ? " *" : ""} (JSON)</label><textarea class="textarea" id="${id}" data-tool-input="${escapeHtml(toolName)}" data-arg="${escapeHtml(name)}" data-type="${type}" placeholder="${type === "array" ? "[]" : "{}"}"></textarea></div>`;
  return `<div class="form-field"><label for="${id}">${escapeHtml(name)}${required ? " *" : ""}</label><input class="input" id="${id}" data-tool-input="${escapeHtml(toolName)}" data-arg="${escapeHtml(name)}" data-type="${escapeHtml(type)}" placeholder="${escapeHtml(schema.description || schema.default || "")}"></div>`;
}

function bindToolActions(tools) {
  document.querySelectorAll("[data-run-tool]").forEach((button) => button.addEventListener("click", async () => {
    const toolName = button.dataset.runTool;
    const tool = tools.find((item) => item.name === toolName);
    const args = {};
    const required = new Set(tool.parameters?.required || []);
    try {
      document.querySelectorAll(`[data-tool-input="${CSS.escape(toolName)}"]`).forEach((input) => {
        if (input.dataset.type === "boolean") {
          args[input.dataset.arg] = input.checked;
          return;
        }
        let value = input.value.trim();
        if (!value) {
          if (required.has(input.dataset.arg)) throw new Error(`${input.dataset.arg} is required`);
          return;
        }
        if (["object", "array"].includes(input.dataset.type)) value = JSON.parse(value);
        else if (input.dataset.type === "integer") value = Number.parseInt(value, 10);
        else if (input.dataset.type === "number") value = Number.parseFloat(value);
        args[input.dataset.arg] = value;
      });
      button.disabled = true;
      const result = await api.call(toolName, args);
      const target = document.querySelector(`[data-tool-result="${CSS.escape(toolName)}"]`);
      target.innerHTML = `<pre class="code-block section">${escapeHtml(JSON.stringify(result.result, null, 2))}</pre>`;
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }));
}
