import { api } from "../api.js";
import { emptyState, escapeHtml, hydrateIcons, loadingState, setHeader, statusBadge } from "../ui.js";

export async function renderTrace(container) {
  setHeader("Call trace", "Every MCP tool call this console has made, from a page or from the assistant");
  container.innerHTML = loadingState();
  await draw(container);
}

async function draw(container) {
  const data = await api.trace();
  const records = data.records || [];
  container.innerHTML = `
    <div class="page-heading">
      <div><div class="eyebrow">Observability</div><h2>${records.length} call${records.length === 1 ? "" : "s"} this session</h2><p>${data.dropped_older_records ? "Older records were dropped -- the trace is bounded." : "In memory for this session only; nothing is written to disk."}</p></div>
      <button class="button button-secondary" id="clearTrace">Clear trace</button>
    </div>
    <div id="traceList"></div>`;
  document.getElementById("clearTrace").addEventListener("click", async () => {
    await api.clearTrace();
    await draw(container);
  });
  const list = document.getElementById("traceList");
  if (!records.length) {
    list.innerHTML = emptyState("No calls yet", "Browse a page or ask a question -- every tool call will appear here.");
    return;
  }
  list.innerHTML = `<div class="tool-explorer">${records.slice().reverse().map(recordRow).join("")}</div>`;
  hydrateIcons(list);
}

function recordRow(record) {
  const failed = record.outcome !== "ok";
  const flags = [
    record.truncated && "truncated",
    record.has_more && "more available",
    record.fanout_capped && "fan-out capped",
    record.compacted && "compacted",
    record.complete && "complete",
  ].filter(Boolean).join(" · ");
  return `<details class="tool-card">
    <summary>
      <div class="tool-name">#${record.id} ${escapeHtml(record.tool)} ${statusBadge(failed ? "critical" : "healthy")}</div>
      <div class="tool-description">${record.elapsed_ms.toFixed(1)} ms · ${record.bytes} bytes · ${escapeHtml(record.outcome)}${flags ? " · " + escapeHtml(flags) : ""}${record.question_id ? ` · from question ${escapeHtml(record.question_id)}` : ""}</div>
    </summary>
    <div class="tool-body">
      <div class="help-text">Arguments as sent</div>
      <pre class="code-block">${escapeHtml(JSON.stringify(record.arguments, null, 2))}</pre>
      ${record.error ? `<div class="help-text">Error</div><pre class="code-block">${escapeHtml(JSON.stringify(record.error, null, 2))}</pre>` : ""}
    </div>
  </details>`;
}
