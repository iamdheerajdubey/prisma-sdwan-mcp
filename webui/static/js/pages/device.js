import { api } from "../api.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, setHeader, statusBadge, toast } from "../ui.js";

export async function renderDevice(container) {
  setHeader("Device view", "The controller's record of a device, next to the device's own report");
  container.innerHTML = `
    <div class="page-heading"><div><div class="eyebrow">Two-lane view</div><h2>Controller vs. device</h2><p>Each lane is a separate tool call, labeled with its source. Neither is ever merged into the other.</p></div></div>
    <div class="toolbar">
      <input class="input" id="deviceElement" placeholder="Element name or ID (e.g. AMS-ION-01)" style="max-width:280px">
      <input class="input" id="deviceSite" placeholder="Site (optional, to disambiguate)" style="max-width:220px">
      <button class="button" id="deviceLoad">Load both lanes</button>
    </div>
    <div class="toolbar">
      <textarea class="textarea" id="deviceCommands" placeholder="One ION CLI command per line" rows="2" style="flex:1">dump interface status all</textarea>
      <button class="button button-secondary" id="deviceRunCommands">Run on device</button>
    </div>
    <div class="dashboard-grid section">
      <section class="panel"><div class="panel-header"><div><h3>Controller lane</h3><p><code>get_device_health</code> -- the controller API's record</p></div></div><div id="controllerLane">${emptyState("Not loaded", "Enter an element and load both lanes.")}</div></section>
      <section class="panel"><div class="panel-header"><div><h3>Device lane</h3><p><code>run_commands</code> -- the device's own report over SSH</p></div></div><div id="deviceLane">${emptyState("Not loaded", "Run a command to reach the device directly.")}</div></section>
    </div>`;
  hydrateIcons(container);

  document.getElementById("deviceLoad").addEventListener("click", loadControllerLane);
  document.getElementById("deviceRunCommands").addEventListener("click", loadDeviceLane);

  async function loadControllerLane() {
    const element = document.getElementById("deviceElement").value.trim();
    const site = document.getElementById("deviceSite").value.trim();
    const target = document.getElementById("controllerLane");
    if (!element) {
      target.innerHTML = emptyState("No element given", "Enter an element name or ID first.");
      return;
    }
    target.innerHTML = loadingState();
    try {
      const args = { element };
      if (site) args.site = site;
      const data = await api.call("get_device_health", args);
      target.innerHTML = laneResult("get_device_health", data.result);
    } catch (error) {
      target.innerHTML = laneUnavailable(error);
    }
  }

  async function loadDeviceLane() {
    const element = document.getElementById("deviceElement").value.trim();
    const site = document.getElementById("deviceSite").value.trim();
    const commandsText = document.getElementById("deviceCommands").value;
    const commands = commandsText.split("\n").map((line) => line.trim()).filter(Boolean);
    const target = document.getElementById("deviceLane");
    if (!element) {
      target.innerHTML = emptyState("No element given", "Enter an element name or ID first.");
      return;
    }
    if (!commands.length) {
      target.innerHTML = emptyState("No command given", "Enter at least one ION CLI command.");
      return;
    }
    target.innerHTML = loadingState();
    try {
      const args = { element, commands };
      if (site) args.site = site;
      const data = await api.call("run_commands", args);
      target.innerHTML = laneResult("run_commands", data.result);
    } catch (error) {
      target.innerHTML = laneUnavailable(error);
    }
  }
}

function laneUnavailable(error) {
  const code = error?.detail?.code || "error";
  return `<div class="info-box"><h4>This lane is unavailable</h4><p><strong>${escapeHtml(code)}</strong>: ${escapeHtml(error.message)}</p></div>`;
}

function laneResult(tool, result) {
  return `<div class="help-text">Source: <code>${escapeHtml(tool)}</code></div><pre class="code-block section">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
}
