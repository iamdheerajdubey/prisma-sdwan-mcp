# Live Validation / Completion Checklist

This file lists what still needs a real Prisma SD-WAN environment or the vendor SDK installed. The codebase is complete enough to run core unit tests without those dependencies, but production cutover should not happen until this checklist passes.

## What was tested during build

The following tests were run successfully in the build environment:

```bash
PYTHONPATH=. pytest -q
```

They cover registry load/counts, action references, resolver ambiguity, GET/POST dispatch using a fake SDK, schema-hint normalization, redaction, and cursor pagination.

Python compilation also passes for the full package.

## What could not be tested here

The build environment did not have `fastmcp` or `prisma_sase` installed and did not have access to your Prisma SD-WAN tenant. I attempted to install the pinned dependencies, but the build container has no outbound package-network/DNS access, so the real FastMCP/vendor-SDK runtime could not be installed here. Therefore the following require your environment:

1. FastMCP runtime registration/transport behavior.
2. Real `prisma_sase==6.8.1b1` generated method signatures for all 308 registry calls.
3. Authentication and tenant-region behavior.
4. Live response shapes and tenant-specific permissions.
5. The eight curated compatibility actions listed below.

## Step 1 - Install and run unit tests

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
PYTHONPATH=. pytest -q
```

Expected: all core tests pass.

## Step 2 - Configure credentials

Copy `.env.example` to `.env` and set:

```text
PAN_CLIENT_ID
PAN_CLIENT_SECRET
PAN_TSG_ID
```

Do not set `MCP_ALLOW_UNVERIFIED_COMPAT=true` yet.

## Step 3 - Start MCP v2

```bash
prisma-sdwan-mcp --transport stdio
```

Confirm startup reports:

```text
308 registry actions + 8 curated compatibility actions
```

## Step 4 - Basic semantic smoke tests

Use real names from your tenant.

1. `find_site(name=<known-site>)`
2. `find_element(name=<known-ion>)`
3. `get_inventory(kind="sites")`
4. `get_device_health(element=<known-ion>)`
5. `get_interfaces(element=<known-ion>, mode="both")`
6. `get_routing(operation="bgp_status", element=<known-ion>)` on a BGP-enabled device.
7. `get_network_services(operation="ntp", element=<known-ion>)`.
8. `get_policies(family="network", operation="sets")`.

Check that names resolve correctly and ambiguous names never auto-select.

## Step 5 - Verify central redaction

Run read-only calls that may contain credentials/config secrets, for example IPsec profile/config, SNMP-related objects, current user/profile-like data, or external CA data.

No returned JSON should expose values whose key contains:

- secret
- token
- session_id
- private_key
- passphrase
- password
- community_string

The value should be `[REDACTED]`.

## Step 6 - Validate the eight curated compatibility actions

These calls fill gaps in the generated 308-action registry and were added by hand. They are the highest-priority live tests.

### A. `compat.topology`

Semantic test:

```text
get_topology()
```

Expected: AnyNet nodes/links are returned and path IDs are visible.

### B. `compat.vpnlinks_status`

Use a vpnlink leg ID from topology:

```text
get_wan(operation="vpn_leg_status", object_id=<leg-id>)
```

Expected: live fields such as active/usable/link_up and endpoint IDs when the controller supplies them.

### C. `compat.vpnlinks_state`

```text
get_wan(operation="vpn_leg_state", object_id=<leg-id>)
```

Expected: administrative state including `enabled` and parent link key when supplied.

### D. `compat.events_query`

```text
get_monitoring(operation="events", site=<site>)
get_monitoring(operation="alarms", site=<site>)
```

Then repeat with a tight `start_time`/`end_time` incident window.

### E. `compat.monitor_flows`

```text
get_monitoring(operation="flows", site=<site>)
get_monitoring(operation="flows", site=<site>, raw=true, limit=20)
```

Confirm the digest fields match the underlying sample.

### F. `compat.monitor_metrics`

```text
get_monitoring(operation="link_metrics", site=<site>)
```

Confirm bandwidth series are returned.

### G. `compat.monitor_lqm_point_metrics`

Same `link_metrics` call. Confirm path-level latency/loss/jitter/MOS content is present when LQM data exists.

### H. `compat.monitor_probe_point_metrics`

```text
get_monitoring(operation="probe_metrics", site=<site>)
```

Confirm configured probes are returned or a valid empty result is produced when no probes exist.

### Status: completed 2026-08-07

All eight were executed against a live tenant during the round-2 AI-consumption
audit, through both `read_capability` and their semantic tools, and returned
correct data. Consequently:

- `requires_live_test` is `false` for all eight in `curated_capabilities.json`;
- `expert_blocked_by_default` in `registry_overrides.yaml` is now empty, so
  `read_capability` executes them without `MCP_ALLOW_UNVERIFIED_COMPAT`;
- their `body_schema` entries were filled in from the request bodies the
  semantic tools actually send, so `list_capabilities` now shows a caller what
  each one requires instead of an untyped object.

Two behaviors were fixed as a result and are worth knowing when re-testing:
the point-metric actions (`compat.monitor_lqm_point_metrics`,
`compat.monitor_probe_point_metrics`) reject a snapshot anchored at "now" as a
future timestamp — anchor at least one interval in the past; and
`compat.topology` accepts only `type: "anynet"`, which is **not** the same
vocabulary as `get_topology`'s `view` argument.

A future curated action that ships unverified must set `requires_live_test: true`
**and** be listed in `expert_blocked_by_default` — the gate reads the list, not
the flag. `MCP_ALLOW_UNVERIFIED_COMPAT=true` overrides the list. The semantic
tools use curated actions directly, independent of either.

## Step 7 - Generic registry spot checks

Use `list_capabilities(domain=...)` and `read_capability` across every domain. At minimum test one GET and one POST/query action where each exists.

Important domains to spot-check:

- sites/devices
- security policies
- NAT
- network/priority policy
- performance management
- routing
- multicast
- VPN/WAN
- IPFIX
- identity
- service connections
- platform/Prisma Access

## Step 8 - Validate generated SDK call binding

The executor tries named Python parameters first, then safe fallback call orders. If any action fails with an error similar to:

```text
Unable to bind SDK method ... to registry parameters
```

record:

- `action_id`
- tool call
- actual SDK method signature (`inspect.signature` if available)

Then add an action-specific invocation override rather than hard-coding the endpoint inside a semantic tool. Keep the registry-first design intact.

## Step 9 - Response-size tests

Test large tenants/catalogs:

- sites/elements
- app definitions
- policy rules
- flows
- directory users

Confirm `next_cursor` is returned rather than huge responses or silent truncation.

## Step 10 - Operational sanity check

Run the same operator questions you would ask in real troubleshooting, and manually cross-check a sample of answers against the Prisma SD-WAN controller UI/API directly:

- site lookup
- element lookup
- topology/path resolution
- VPN leg state
- BGP peer/status/prefixes
- static routes
- events/alarms
- flows
- link metrics
- application lookup
- policy sets/zones/WAN networks

Confirm each answer matches what the controller shows, and that the server is never less safe about ambiguity or sensitive fields.

## Production cutover rule

Cut over when:

- core unit tests pass;
- the eight compatibility actions pass;
- no secret leakage is observed;
- representative registry actions pass in every domain;
- operator questions produce accurate answers when cross-checked against the controller directly.

## Step 7 — ION CLI address resolution (2026-08-09)

Read-only validation of `prisma_sdwan_mcp/cli/address.py` against the live
tenant. No SSH session was opened; this step only confirms which address the
**controller API** can produce for a named element.

Sampled device: `IMEMION1` (ion 5200, Memphis HQ), 33 interfaces.

Findings that shaped the implementation:

| Question | Answer |
| --- | --- |
| Does the API expose an ION's IP addresses? | Yes. |
| Where does a **static** address live? | `sites_devices.interfaces` → `ipv4_config.static_config.address`, and also in the status record. |
| Where does a **DHCP** address live? | Status record only. The config record is `{"type": "dhcp"}` with no address at all. `sites_devices.interfaces_status` → `ipv4_addresses` carries the live address for static and DHCP alike, so it is the only source read. |
| Is `admin_up` a liveness signal? | No. True on nearly every interface including physically down ports. `operational_state` from the status record is the real signal. |
| What separates a management address from noise? | `used_for`. On this device: 16 addressed interfaces total, 3 with `used_for` in (`controller`, `lan`), exactly 1 with `controller`. |
| Is `element_status.controller_connection_intf` a usable tie-breaker? | **No.** It pointed at interface `1` — the DHCP public WAN port the device reaches the cloud through. Wrong target for SSH management, and the one interface with no config address. |

Result on `IMEMION1`: interface `17`, `used_for: controller`, `10.175.10.101`,
operationally up — one unambiguous answer.

Sample across 15 site-assigned elements: **14 resolved to exactly one address**
(11 via `controller`, 3 via `lan`). The single failure was `SPARE-2-TESTING`,
an unprovisioned spare with no live management interface — the correct answer.

Still unverified (needs a real SSH attempt, not an API call):

- whether the MCPv2 host can route to these addresses (mostly RFC1918)
- the `--More--` pagination marker
- public-key SSH authentication
