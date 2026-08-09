import { api } from "../api.js";
import { emptyState, escapeHtml, hydrateIcons, setHeader } from "../ui.js";

const DISCLOSURE_KEY = "prisma_console_disclosure_ack";

const SUGGESTIONS = [
  "Which sites have active findings right now?",
  "What is the health of the Amsterdam branch device?",
  "Are any WAN paths down in the topology?",
  "What is Bangalore Office's site status?",
];

export async function renderAsk(container) {
  setHeader("Ask Network", "A real model with the MCP tool set -- not a keyword router");
  const assistantStatus = await api.assistantStatus().catch((error) => ({ available: false, message: error.message }));

  container.innerHTML = `
    <div class="ask-shell">
      <section class="ask-hero">
        <div class="eyebrow">Model-driven assistant</div>
        <h2>What do you need to know?</h2>
        <p>Claude selects and calls the same MCP tools this console uses, against your live tenant. The full call chain is shown with the answer.</p>
        ${assistantStatus.available ? "" : `<div class="info-box"><h4>Question box unavailable</h4><p>${escapeHtml(assistantStatus.message || "No Anthropic API key is configured.")}</p></div>`}
        <div class="ask-input-row">
          <input class="input" id="askInput" placeholder="Why is Amsterdam internet slow?" ${assistantStatus.available ? "" : "disabled"}>
          <button class="button" id="askButton" ${assistantStatus.available ? "" : "disabled"}>Ask network</button>
        </div>
        <div class="ask-suggestions">${SUGGESTIONS.map((text) => `<button class="suggestion" data-question="${escapeHtml(text)}" ${assistantStatus.available ? "" : "disabled"}>${escapeHtml(text)}</button>`).join("")}</div>
      </section>
      <div id="askAnswer"></div>
    </div>`;
  hydrateIcons(container);

  if (!assistantStatus.available) return;

  async function ask(question) {
    question = question.trim();
    if (!question) return;
    if (!ensureDisclosure()) return;

    const target = document.getElementById("askAnswer");
    target.innerHTML = answerShell();
    const answerEl = document.getElementById("answerText");
    const reasoningEl = document.getElementById("answerReasoning");
    const chainEl = document.getElementById("answerChain");
    const statusEl = document.getElementById("answerStatus");
    let answerText = "";
    let reasoningText = "";
    const chainRows = [];

    try {
      await streamAsk(question, (event) => {
        switch (event.type) {
          case "thinking_delta":
            reasoningText += event.text;
            reasoningEl.hidden = false;
            reasoningEl.querySelector(".reasoning-body").textContent = reasoningText;
            break;
          case "answer_delta":
            answerText += event.text;
            answerEl.textContent = answerText;
            break;
          case "active_diagnostic":
            chainRows.push(
              `<div class="finding-row"><span class="severity-bar critical"></span><div><div class="row-title">Active diagnostic: ${escapeHtml(event.tool)}</div>` +
              `<div class="row-subtitle">Sends real packets from the device -- ${escapeHtml(JSON.stringify(event.arguments))}</div></div></div>`
            );
            chainEl.innerHTML = chainRows.join("");
            break;
          case "tool_result":
            chainRows.push(chainRow(event));
            chainEl.innerHTML = chainRows.join("");
            break;
          case "declined":
            statusEl.innerHTML = `<div class="info-box"><h4>The model declined to answer</h4><p>${escapeHtml(event.message)}${event.category ? ` (category: ${escapeHtml(event.category)})` : ""}</p></div>`;
            break;
          case "error":
            statusEl.innerHTML = `<div class="info-box"><h4>${escapeHtml(errorTitle(event.code))}</h4><p>${escapeHtml(event.message)}</p></div>`;
            break;
          case "done":
            if (!chainRows.length) {
              chainEl.innerHTML = emptyState("No tool calls", "This answer was not grounded in any retrieved data.");
            }
            if (event.incomplete) {
              statusEl.innerHTML = `<div class="info-box"><h4>Incomplete -- hit the call ceiling</h4><p>The assistant was still calling tools when it reached its iteration limit. What is shown is partial work, not a finished answer.</p></div>`;
            }
            break;
        }
      });
    } catch (error) {
      statusEl.innerHTML = `<div class="info-box"><h4>Request failed</h4><p>${escapeHtml(error.message)}</p></div>`;
    }
  }

  document.getElementById("askButton").addEventListener("click", () => ask(document.getElementById("askInput").value));
  document.getElementById("askInput").addEventListener("keydown", (event) => { if (event.key === "Enter") ask(event.target.value); });
  container.querySelectorAll("[data-question]").forEach((button) => button.addEventListener("click", () => {
    document.getElementById("askInput").value = button.dataset.question;
    ask(button.dataset.question);
  }));
}

function answerShell() {
  return `<div class="answer-card">
    <div id="answerStatus"></div>
    <p id="answerText"></p>
    <details id="answerReasoning" hidden><summary class="text-button">Reasoning summary</summary><pre class="code-block reasoning-body"></pre></details>
    <section class="section">
      <div class="section-header"><div><h3>Call chain</h3><p>Every tool call behind this answer, in order</p></div></div>
      <div id="answerChain" class="finding-list panel"></div>
    </section>
  </div>`;
}

function chainRow(event) {
  const failed = event.outcome !== "ok";
  return `<div class="finding-row"><span class="severity-bar ${failed ? "critical" : "healthy"}"></span><div><div class="row-title">${escapeHtml(event.tool)}</div><div class="row-subtitle">${escapeHtml(JSON.stringify(event.arguments))}</div></div><div class="row-meta hide-mobile">${escapeHtml(event.outcome)} · trace #${event.trace_id}</div></div>`;
}

function errorTitle(code) {
  return {
    configuration_error: "No API key configured",
    authentication_error: "API key rejected",
    rate_limited: "Rate limited",
    provider_unavailable: "Model provider unavailable",
    provider_error: "Model provider error",
    transport_error: "MCP session unreachable",
    invalid_argument: "Enter a question",
    empty_response: "No response",
  }[code] || "Error";
}

function ensureDisclosure() {
  if (sessionStorage.getItem(DISCLOSURE_KEY) === "1") return true;
  const proceed = confirm(
    "Questions you type here, and the tool results retrieved to answer them, are sent to Anthropic (the model provider). " +
    "This can include tenant topology and device output. Continue?"
  );
  if (proceed) sessionStorage.setItem(DISCLOSURE_KEY, "1");
  return proceed;
}

async function streamAsk(question, onEvent) {
  const response = await fetch("/api/assistant/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.body) throw new Error(`Request failed (${response.status})`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index);
      buffer = buffer.slice(index + 1);
      if (!line.trim()) continue;
      try {
        onEvent(JSON.parse(line));
      } catch {
        // Ignore a malformed line rather than aborting the whole stream.
      }
    }
  }
}
