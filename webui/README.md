# Prisma SD-WAN network console

A local, single-operator web console for `prisma-sdwan-mcp` -- browse the tool surface, inspect
live results, and (optionally) ask a real model a question. It speaks MCP over stdio to the
server exactly like Claude Desktop does; it never imports `prisma_sdwan_mcp`.

## Install and run

```bash
pip install -e ".[webui]"     # from the repo root -- adds anthropic[mcp] on top of the base install
python webui/server.py
```

Open `http://127.0.0.1:8766/`. The console spawns `prisma-sdwan-mcp --transport stdio` itself, so
make sure the server's own environment (`PAN_CLIENT_ID` / `PAN_CLIENT_SECRET` / `PAN_TSG_ID`, and
optionally the `PRISMA_ION_*` variables) is already configured -- the console has no credential
form of its own for the Prisma tenant. Preview mode works with none of that configured at all.

`--host` / `--port` override the bind address and port (defaults: `127.0.0.1:8766`, or
`PRISMA_CONSOLE_HOST` / `PRISMA_CONSOLE_PORT`).

## The two things a console can show that a chat client can't

- **Call trace** (`Call Trace` in the nav): every MCP tool call this process has made -- page or
  assistant -- with its arguments, elapsed time, byte size, and whether the server reports it
  truncated, paged, or fan-out capped. In-memory only, bounded, cleared on request or process exit.
- **Device view** (`Device View` in the nav): the controller's answer and the device's own answer
  for the same element, side by side, each labeled with the tool that produced it. Depends on
  `run_commands` being SSH-reachable from wherever the console runs -- see the root README's ION
  CLI section. If it isn't, that lane says so and the controller lane still works.

## The question box

Bring-your-own Anthropic API key, pasted in Administration > API key. It is held in this process's
memory only -- never written to disk, never logged, never returned by any endpoint -- and is gone
on restart. `ANTHROPIC_API_KEY` in the environment is used as a fallback for local development.
With no key available, the question box is disabled with an explicit message; every other page
keeps working.

The model (`claude-opus-5`) gets the live MCP tool set and picks which tools to call, against their
declared schemas -- there is no keyword table deciding this. Before the first question in a browser
session, the console discloses that the question text and the tool results gathered to answer it
are sent to Anthropic; declining leaves the rest of the console usable.

## What this is not

- Not authenticated. Anything that can reach the bound address can drive your live tenant through
  it and read the trace. Loopback bind is the mitigation -- the server prints a warning to stderr
  if started on a non-loopback address, and the API key crosses that address from the browser in
  plaintext regardless of bind address.
- Not a place that writes anything. All 27 tools it can call are read-only or active-diagnostic
  (`run_commands`'s `ping`/`tcpping`/`dig`); there is no mutation path, and the console itself holds
  no state beyond the in-memory trace and key, both cleared on exit.
- Not a second copy of the Prisma SD-WAN controller UI. It doesn't try to be a dashboard.

## What was deliberately not ported from `webtester`, and why

This is a rewrite of webtester's "Ask Network" half, not a port of it -- ported code from the other
half (design system, Preview mode, tool explorer, `normalizer.py`) sits next to it. If you're
looking at the old `D:\Prisma-MCP\webtester` repo and wondering why something here looks different:

- **`app/catalog.py` (`INTENT_RULES`) -- deleted, not ported.** A hand-written keyword-to-tool
  scoring table. This is the exact pattern the `catalog-browse-not-search` change removed from the
  server one layer down: substring-matching an operator's phrasing against tool prose fails
  silently on ordinary rephrasing, and the caller can't tell "unsupported" from "asked it wrong."
- **`app/workflows.py`'s `_build_args` and `ask()` -- deleted, not ported.** `_build_args` guessed a
  tool's arguments by matching parameter *names* against a generic context dict; `ask()` was the
  keyword chain that routed a free-text question to `catalog.py`'s ranked tools. The question box
  now gives the model the real tool schemas and lets it choose; the rest of `workflows.py` (the
  per-page functions, the TTL cache) survives, rewritten to call one specific, known tool per page
  instead of a ranked fan-out across tools it discovered at runtime.
- **`app/mcp_gateway.py` -- deleted, not ported.** Imported `prisma_sdwan_mcp` in-process and called
  `tool.fn(**args)` directly. That's what let webtester reach `registry.client`, and what broke
  outright when `registry` became `runtime` in this repo. `app/mcp_client.py` replaces it, speaking
  the protocol instead.
- **The `/api/connect` endpoint and the Administration "Connection" credential form -- not ported.**
  Webtester let the browser POST Prisma credentials, which it then wrote into `os.environ` for an
  in-process SDK client. Those credentials belong to the MCP server subprocess's own environment
  now, not to the console -- the console has no path to set them, and setting a subprocess's
  environment from the parent after the fact isn't a thing this design does anywhere (see the API
  key section above for the one credential the console *does* hold, and why it's handled
  differently). Administration > Connection is now a read-only view of the MCP session's state.
- **The "Capabilities" admin tab -- not ported.** It rendered `catalog.py`'s intent-to-tool ranking
  as a table -- a visualization of the exact pattern above. The MCP tool explorer (`Administration >
  MCP tool explorer`) already shows the real tool set with real schemas; a second tab restating a
  deleted guess isn't a replacement worth building.
- **Its standalone `server.py` entrypoint wiring and the "customer-facing portal" framing --
  not ported.** Not a hard technical reason -- Palo Alto ships a controller UI with better
  dashboards, and Overview/Sites/Findings/Telemetry/Resources were kept only where they show
  something worth showing next to the trace and device views, not because they were free to carry
  over.

## Tests

```bash
PYTHONPATH=. pytest -q tests/test_webui_*.py
```

Two of these files need the `webui` extra installed (`anthropic`) and skip without it, so the
repo's dependency-free core suite (`PYTHONPATH=. pytest -q`) still passes on a base install.
Run only those with `-m webui`, or exclude them with `-m "not webui"`.

Offline, no live tenant and no Anthropic key required -- everything that talks to the MCP session
or the model is stubbed. `tests/test_webui_mcp_client.py` also asserts, by walking every `.py` file
under `webui/`, that nothing here imports `prisma_sdwan_mcp`.
