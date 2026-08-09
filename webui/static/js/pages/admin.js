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
  if (tab === "assistant") return renderAssistant(target);
  return renderTools(target);
}

async function renderConnection(target) {
  let status;
  try { status = await api.liveStatus(); } catch (error) { status = { connected: false, error: error.message }; }
  target.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">MCP session</div><h2>Connection</h2><p>The console is an MCP client over stdio to <code>prisma-sdwan-mcp</code> -- the same relationship Claude Desktop has. Credentials for the Prisma tenant belong to that server process, not to this console; configure them in its own environment before starting the console.</p></div></div>
    <div class="info-box"><h4>Current state</h4><p>${status.connected ? `Connected. ${status.tool_count ?? "?"} tool(s) available.` : `Not connected${status.error ? `: ${escapeHtml(status.error)}` : "."}`}</p></div>
    ${status.command ? `<div class="info-box section"><h4>Spawned command</h4><p><code>${escapeHtml(status.command.join(" "))}</code></p></div>` : ""}
    <div class="form-actions section"><button class="button button-secondary" type="button" id="usePreviewButton">Use preview mode instead</button></div>
    <p class="help-text">Preview mode never makes a live call -- it is backed entirely by sample data.</p>`;
  document.getElementById("usePreviewButton").addEventListener("click", () => {
    setMode("demo");
    toast("Preview mode enabled.", "success");
    document.dispatchEvent(new CustomEvent("portal:connection-changed"));
  });
}

async function renderAssistant(target) {
  let status;
  try { status = await api.assistantStatus(); } catch (error) { status = { available: false, message: error.message }; }
  target.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Question box</div><h2>Anthropic API key</h2><p>Held only in this running process -- never written to disk, never logged, never returned by any endpoint. Restarting the console requires supplying it again.</p></div></div>
    <div class="info-box"><h4>Current state</h4><p>${status.available ? "A key is configured. The question box is enabled." : escapeHtml(status.message || "No key is configured. The question box is disabled.")}</p></div>
    <form id="assistantKeyForm" class="section">
      <div class="form-grid">
        <div class="form-field full"><label for="assistantKeyInput">Anthropic API key</label><input class="input" type="password" id="assistantKeyInput" autocomplete="off" placeholder="sk-ant-..."></div>
      </div>
      <div class="form-actions"><button class="button" type="submit">Save key</button><button class="button button-secondary" type="button" id="assistantKeyClear">Clear key</button></div>
      <p class="help-text">The key crosses loopback HTTP from your browser to this server in plaintext -- acceptable on a single-user machine, not on a shared one. An <code>ANTHROPIC_API_KEY</code> environment variable is used as a fallback if no key is pasted here.</p>
    </form>`;
  document.getElementById("assistantKeyForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      await api.setAssistantKey(document.getElementById("assistantKeyInput").value);
      toast("API key saved for this session.", "success");
      renderAssistant(target);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById("assistantKeyClear").addEventListener("click", async () => {
    await api.clearAssistantKey();
    toast("API key cleared.", "success");
    renderAssistant(target);
  });
}

async function renderTools(target) {
  try {
    cachedTools ||= (await api.tools()).tools || [];
    target.innerHTML = `
      <div class="page-heading"><div><div class="eyebrow">Engineering</div><h2>MCP tool explorer</h2><p>Raw tool access, isolated here for validation and troubleshooting. Runs through the same <code>call_tool</code> path as every page, so it appears in the trace.</p></div></div>
      <div class="toolbar"><div class="search-box"><span data-icon="search"></span><input class="input" id="toolSearch" placeholder="Filter tools"></div></div>
      <div class="tool-explorer" id="toolList"></div>`;
    hydrateIcons(target);
    const draw = () => {
      const query = document.getElementById("toolSearch").value.trim().toLowerCase();
      const tools = cachedTools.filter((tool) => !query || `${tool.name} ${tool.description}`.toLowerCase().includes(query));
      document.getElementById("toolList").innerHTML = tools.map((tool) => toolCard(tool)).join("") || '<div class="info-box"><h4>No matching tools</h4><p>Change the filter.</p></div>';
      bindToolActions(tools);
    };
    document.getElementById("toolSearch").addEventListener("input", draw);
    draw();
  } catch (error) {
    target.innerHTML = `<div class="info-box"><h4>Tool explorer unavailable</h4><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function toolCard(tool) {
  const schema = tool.input_schema || {};
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  return `<details class="tool-card"><summary><div class="tool-name">${escapeHtml(tool.name)}${tool.read_only === false ? ' <span class="status-badge critical">active diagnostic</span>' : ""}</div><div class="tool-description">${escapeHtml((tool.description || "").split("\n")[0])}</div></summary><div class="tool-body"><div class="form-grid">${Object.entries(properties).map(([name, propSchema]) => inputFor(tool.name, name, propSchema, required.has(name))).join("") || '<div class="help-text">No arguments.</div>'}</div><div class="form-actions"><button class="button" data-run-tool="${escapeHtml(tool.name)}">Run tool</button></div><div data-tool-result="${escapeHtml(tool.name)}"></div></div></details>`;
}

function inputFor(toolName, name, schema, required) {
  const id = `tool_${toolName}_${name}`.replace(/[^a-zA-Z0-9_]/g, "_");
  const type = schema.type || "string";
  if (type === "boolean") return `<div class="form-field"><label><input type="checkbox" id="${id}" data-tool-input="${escapeHtml(toolName)}" data-arg="${escapeHtml(name)}" data-type="boolean"> ${escapeHtml(name)}${required ? " *" : ""}</label></div>`;
  if (type === "object" || type === "array") return `<div class="form-field full"><label for="${id}">${escapeHtml(name)}${required ? " *" : ""} (JSON)</label><textarea class="textarea" id="${id}" data-tool-input="${escapeHtml(toolName)}" data-arg="${escapeHtml(name)}" data-type="${type}" placeholder="${type === "array" ? "[]" : "{}"}"></textarea></div>`;
  return `<div class="form-field"><label for="${id}">${escapeHtml(name)}${required ? " *" : ""}</label><input class="input" id="${id}" data-tool-input="${escapeHtml(toolName)}" data-arg="${escapeHtml(name)}" data-type="${escapeHtml(type)}" placeholder="${escapeHtml(schema.description || "")}"></div>`;
}

function bindToolActions(tools) {
  document.querySelectorAll("[data-run-tool]").forEach((button) => button.addEventListener("click", async () => {
    const toolName = button.dataset.runTool;
    const tool = tools.find((item) => item.name === toolName);
    const args = {};
    const required = new Set((tool.input_schema || {}).required || []);
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
