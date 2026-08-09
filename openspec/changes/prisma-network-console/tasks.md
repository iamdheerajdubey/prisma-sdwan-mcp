## 1. Scaffold and dependencies

- [x] 1.1 Create `webui/` beside `prisma_sdwan_mcp/` with `app/` and `static/` subdirectories; no `__init__.py` exposure that would make it importable as part of the server package.
- [x] 1.2 Add a `webui` optional extra to `pyproject.toml` pulling `anthropic[mcp]` and the MCP client library; confirm `pip install -e .` (without the extra) resolves to exactly today's dependency set.
- [x] 1.3 Port `webtester/server.py` to `webui/server.py`: stdlib HTTP server, static file serving, JSON API routing, loopback bind by default, debug tracebacks off by default. Drop the credential-into-`os.environ` path entirely.
- [x] 1.4 Add `--host` / `--port` arguments with a startup warning printed to stderr whenever the bind address is not loopback.

## 2. MCP client transport

- [x] 2.1 Create `webui/app/mcp_client.py`: open one MCP stdio session against `prisma-sdwan-mcp`, expose `list_tools()` and `call_tool(name, args)`, and manage subprocess lifetime including clean shutdown.
- [x] 2.2 Verify no module in `webui/` imports `prisma_sdwan_mcp` — add a test that asserts it, so the in-process shortcut cannot come back.
- [x] 2.3 Map failures into three distinguishable classes: transport/session failure, tool-returned structured error, and empty-but-successful result.
- [x] 2.4 Pass ambiguous-match candidates through to the caller intact so the UI can offer them as a choice.
- [x] 2.5 Add `tests/test_webui_mcp_client.py` with a stubbed session covering all three failure classes plus the ambiguity path.

## 3. Call trace

- [x] 3.1 Create `webui/app/trace.py`: an in-memory bounded ring of records, no disk writes, clearable, with a flag indicating when older records were dropped.
- [x] 3.2 Record from inside `call_tool` so page-initiated and assistant-initiated calls produce identical records through one path.
- [x] 3.3 Capture per record: tool, arguments as sent, elapsed, returned byte size, outcome, and the question ID when the call came from the assistant.
- [x] 3.4 Read truncation, `next_cursor`, fan-out capping, and compaction flags out of the response envelope onto the record; mark a response with none of them explicitly complete.
- [x] 3.5 Redact credential-bearing argument values in the record and never store the raw value.
- [x] 3.6 Add `tests/test_webui_trace.py` covering: complete vs truncated, cursor present, fan-out capped, credential redaction, ring eviction with the dropped-records flag.

## 4. Assistant

- [x] 4.1 Create `webui/app/assistant.py`: convert MCP tools with the SDK's MCP helpers and drive `client.beta.messages.tool_runner` — `claude-opus-5`, adaptive thinking with `display: "summarized"`, `effort` from config (default `xhigh`), streamed, `max_tokens` 64000.
- [x] 4.2 Hold the API key in a module-level in-memory value set via an Administration endpoint; fall back to `ANTHROPIC_API_KEY` if already present in the environment. Pass it to the client constructor — never assign it into `os.environ`.
- [x] 4.3 Fail closed with a `configuration_error`-shaped response when no key is available, leaving every other endpoint working; expose key presence as a boolean and never the value.
- [x] 4.4 Place a prompt-cache breakpoint after the tool definitions and system prompt; serialize the tool list deterministically and keep anything volatile after the breakpoint.
- [x] 4.5 Enable `fallbacks: "default"` under the server-side fallback beta, and check `stop_reason` before reading response content.
- [x] 4.6 Bound the loop with an iteration ceiling; on hitting it, return the partial work labeled incomplete rather than as an answer.
- [x] 4.7 Use the runner's per-turn hook to surface a tool whose annotations mark it non-read-only before it executes, so an active diagnostic is not run indistinguishably from a read.
- [x] 4.8 Emit the ordered call chain with every answer, including failed calls, each linked to its trace record; state explicitly when an answer involved no tool calls.
- [x] 4.9 Map provider outcomes to distinguishable results: declined, authentication rejected, rate-limited/unavailable, and success — never a fabricated or partial answer in place of a failure.
- [x] 4.10 Add `tests/test_webui_assistant.py` with a stubbed model client covering: tool selection reaching the real tool set, the iteration ceiling, refusal, auth rejection, rate limiting, the no-calls case, and the fail-closed no-key path.
- [x] 4.11 Add a test asserting no API key value appears in any response body, log line, or trace record on any path.

## 5. Front end — ported shell

- [x] 5.1 Port `static/css/tokens.css`, `static/css/app.css`, `static/index.html`, `static/js/{app,ui,api,details}.js` largely as-is.
- [x] 5.2 Port `demo.py` and the Preview toggle; add a test asserting no MCP call is issued while Preview is active.
- [x] 5.3 Make the Preview indicator continuous rather than momentary, and clear results when switching modes so stale data cannot be relabelled.
- [x] 5.4 Port the Administration drawer and its MCP tool explorer; add the API-key panel (paste, clear, presence indicator) alongside Connection and Capabilities.
- [x] 5.5 Port `normalizer.py` unchanged and add a test pinning its status/severity mapping against representative payloads.
- [x] 5.6 Port the existing pages (Overview, Sites, Findings, Telemetry, Resources) onto the new client, then review each against the trace and device views and cut what no longer earns its place.

## 6. Front end — new views

- [x] 6.1 Build the trace panel: one row per call with tool, elapsed, bytes, and status; expandable to arguments and the truncation/cursor/fan-out state; a clear control.
- [x] 6.2 Rewrite `pages/ask.js` against the assistant endpoint: streamed answer, summarized reasoning, the call chain, and per-call links into the trace.
- [x] 6.3 Add the first-use disclosure that question text and retrieved tool results are sent to the model provider; nothing is sent until the user proceeds, and declining leaves the rest of the console usable.
- [x] 6.4 Build the two-lane device view: controller result and device result side by side, each labeled with its source and the tool that produced it.
- [x] 6.5 When one lane is unavailable — no device credentials, unreachable, failed call — say so and why, and still render the other lane.

## 7. Documentation

- [x] 7.1 Write `webui/README.md`: install with the extra, run it, the in-memory key model, and the loopback-bind and plaintext-key warnings stated plainly.
- [x] 7.2 Update `README.md` and `docs/ARCHITECTURE.md` to describe the console as a second MCP consumer alongside Claude Desktop, not part of the server.
- [x] 7.3 Record in `webui/README.md` what was deliberately not ported from webtester and why, so it isn't re-added by someone who finds the old repo.
- [x] 7.4 Confirm nothing from `webtester/` carrying credentials or tenant identifiers was copied into this repo.

## 8. Verification

- [x] 8.1 Run the full suite (`PYTHONPATH=. pytest -q`) and confirm no existing test changed behavior and the base install still needs no new dependency.
- [ ] 8.2 Exercise the console end to end against the live tenant: browse, inspect, ask a question, read the trace, and open the device lane. **Skipped — needs a live tenant.**
- [ ] 8.3 Sweep `effort` (`medium` / `high` / `xhigh`) across a fixed set of troubleshooting questions; record cost, latency, and answer quality, then set the default from the result rather than the starting assumption. **Skipped — needs a live tenant and an Anthropic key to run real questions against.**
- [ ] 8.4 Confirm prompt caching is actually hitting — repeated questions in one session should show cache reads rather than full-price input on the tool prefix. **Skipped — needs a live Anthropic key.**
- [ ] 8.5 Confirm the two-lane view against a device that is actually SSH-reachable, or record that it is not and that the lane degrades as specified. **Skipped — needs a live tenant and a reachable ION.**
