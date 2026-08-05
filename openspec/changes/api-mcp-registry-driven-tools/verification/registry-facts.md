# Registry facts, measured

Everything below was measured against the checked-out registry files and
`prisma_sase 6.8.1b1` on 2026-08-05. It corrects several assumptions the first draft
of proposal.md / design.md was written on. Reproduce with the snippets in each row.

## Counts

| Claim in the draft | Measured | Note |
|---|---|---|
| 202 GET actions (also the GET file's own `metadata.total_actions`) | **203 entries, 202 unique names** | `elementusers` is listed under two domains. The metadata counts unique names; the dispatcher registers entries. The loader must count entries itself, not read `metadata`. |
| 106 POST actions | 106 | Matches. |
| 308 total | **309** | Consequence of the above. |
| "~33 domains" → 18 GET tools + 15 POST tools | **18 domain names total** | All 15 POST domain names already exist in the GET registry. GET-only extras: `device_diagnostics`, `monitoring_aiops`, `service_connections_extensions`. |
| 39 hand-written tools | 39 | Matches `EXPECTED_SIGNATURES`. |

No action name is duplicated inside a domain, and no GET action name collides with a
POST action name inside the same domain — so one MCP tool per domain, carrying both
its GET and its POST actions, works without a namespacing scheme.

## Resolvability against the live SDK

| Check | Result |
|---|---|
| GET actions whose `name` resolves as `sdk.get.<name>` | **203 / 203** |
| POST actions whose `sdk_call` resolves as `sdk.post.<sdk_call>` | **106 / 106** |

The GET registry has **no `sdk_call` field at all** — its `name` *is* the SDK method
name. design.md described a single `{name, sdk_call, url_template, parameters, safety}`
shape; that shape only describes the POST file.

## The two files do not share a schema

| Field | GET | POST |
|---|---|---|
| `sdk_call` | absent | present |
| `input_parameters` | **absent on all 203** | present |
| `api_version`, `category` | absent | present |
| `safety.verified_using_a_real_chained_id` | present | absent |

So `safety` is a 4-key object in the GET file and a 3-key object in the POST file.
A gate written as `safety == {read_only, destructive, verified_working}` — exact
equality, as design.md decision 2 and spec.md both specified — **excludes all 203 GET
actions**, leaving a server with zero GET coverage. The gate must require those three
keys to be `true` and ignore additional keys.

## `verified_working` is weaker for GET than the draft assumed

| GET actions | Count |
|---|---|
| Total | 203 |
| Need no path parameter | 26 |
| Have only optional path parameters | 74 |
| **Have a required path parameter** | **103** |
| Carry `verified_using_a_real_chained_id: true` | **31** |

All 203 carry `read_only/destructive/verified_working = true/false/true`. But 103 of
them require an ID, and only 31 were ever exercised with a real one. The remaining
~72 are marked "verified working" on the strength of a call that never supplied the
identifier the endpoint needs. Treat `verified_working: true` on a GET action with a
required path parameter as *unverified*, and say so in the audit resource.

## Coverage gap: 9 SDK calls the current tools depend on are in neither registry

```
GET  : element_status, vpnlinks_state, vpnlinks_status
POST : events_query, monitor_flows, monitor_metrics,
       monitor_lqm_point_metrics, monitor_probe_point_metrics, topology
```

Eleven of the 39 tools are built on them — and they are the troubleshooting-critical
ones:

| Tool | Missing SDK call(s) |
|---|---|
| `get_element_status` | `element_status` |
| `get_events` | `events_query` |
| `get_alarms` | `events_query` |
| `get_flows` | `monitor_flows` |
| `get_link_metrics` | `monitor_lqm_point_metrics`, `monitor_metrics` |
| `get_probe_metrics` | `monitor_probe_point_metrics` |
| `get_topology` | `topology` |
| `get_site_paths` | `topology` |
| `get_basenet_topology` | `topology`, `vpnlinks_status` |
| `get_vpnlink_status` | `vpnlinks_status` |
| `get_vpnlink_state` | `vpnlinks_state` |
| `resolve_path` | `topology` |

The registries are a catalogue of `/query`-style and plain-collection endpoints. They
do not include the metrics/flows/topology/events surface. Any plan that retires
"pass-through" tools by domain would delete these outright: **the dispatcher cannot
serve them, because the calls they make are not in the registry.**

## `input_parameters` cannot be used as a closed allow-list

Every POST `input_parameters` entry carries this note verbatim:

> "Optional filter/sort field observed from this endpoint's response hints. Not exhaustive."

They were harvested from `next_query` hints in observed responses, so a field is only
listed if the controller happened to echo it. The SDK's own docstrings advertise more
(`aggregate`, `dest_page`, `group_by`, `query_params`, `filter`, …) than the registry
records. Rejecting any `params` key the registry does not declare — as spec.md
required — would reject legitimate queries. The GET file has no `input_parameters` at
all, so for GET there is nothing to validate against in the first place.

## fastmcp 3.4.4: no per-action dynamic schema (design.md Open Question 1, answered)

`fastmcp.tools.tool.Tool` carries a static `parameters` field fixed at registration;
`FastMCP.tool()` and `Tool.from_function()` expose `output_schema` but no input-schema
hook that varies with an argument's *value*, and `list_tools()` returns one fixed
schema per tool. MCP itself has no concept of a schema that changes per call. **Answer:
not supported, and not a fastmcp limitation to wait out.** The docstring-based
discoverability approach is the design, not a placeholder.

## Audit log unavailable

`GET /auditlog` and `POST /auditlog/query` both return **403** for this service
account. It is the natural detector for "did anything write?", so its absence is worth
recording before someone designs a check around it.

## Consumer impact: webtester needs a change after all

proposal.md claimed "no code change required". Measured against the code:

- `webtester/app/mcp_gateway.py:76` derives a tool's category from
  `tool.fn.__module__`. Register 18 domain tools from one dispatcher module and every
  tool lands in one category.
- `webtester/app/catalog.py:61,88` scores tools by hardcoded category names
  (`inventory`, `resolve`, `network`, `routing`, `monitoring`). A single dispatcher
  category matches none of them, losing the +5 bonus for every tool.
- `webtester/app/catalog.py:92` adds +3 for names starting `get_`/`list_`/`query_`/
  `search_`/`resolve_`. Domain names like `sites_devices` match none.
- `webtester/app/catalog.py:80` returns score 0 when no positive term hits, and
  `rank_tools` drops anything scoring ≤ 0 — so tools can disappear from the ranked UI
  pages entirely rather than merely rank lower.

Nothing crashes and no tool name is hardcoded, so the *gateway* is genuinely dynamic.
The *catalogue heuristics* are not, and they are what the UI is built on.
