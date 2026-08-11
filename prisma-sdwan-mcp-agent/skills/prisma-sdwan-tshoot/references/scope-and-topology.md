# Scope, Alert Semantics, and Topology

## Contents

- Purpose and accepted input
- Input normalization
- SOP alert semantics
- Entity resolution
- ID discipline
- Topology workflow
- Two-endpoint handling
- Incident-time handling

## Purpose

Convert free-form event text into a precise diagnostic scope before collecting deep evidence.

## Acceptable input

The user may provide anything from a complete controller event to a sentence such as:

- "Branch A is down."
- "Site A to Site B tunnel is flapping."
- "SITE_CONNECTIVITY_DEGRADED at Johannesburg."
- "NETWORK_ANYNETLINK_DEGRADED between Branch-A and DC-1."
- "Users at Site X have high loss but tunnels look up."

Do not require an ITSM envelope, event number, `unique_id`, or pre-parsed JSON.

## Normalize the report

Extract only facts actually present:

- symptom/impact;
- alert type, if supplied;
- site name(s) or IDs;
- element/device name(s) or IDs;
- AnyNet/tunnel/path identifier, if supplied;
- incident timestamp/window, if supplied;
- directionality or affected circuit, if supplied.

Treat missing fields as unknown, not null facts.

## SOP alert semantics

### `SITE_CONNECTIVITY_DOWN`

Use as a **site-wide critical-outage hint**. The SOP associates it with all secure fabric links being down and controller disconnection for a sustained period at a branch, or all remote sites being unreachable at a data-center site. Verify current/history evidence rather than assuming this condition still exists.

Primary fault domains to test:

1. device/power/HA;
2. all usable WAN underlays;
3. controller reachability/control plane;
4. overlay only after the local device and underlay are credible.

### `SITE_CONNECTIVITY_DEGRADED`

Use as a **partial-connectivity hint**. The SOP associates it with multiple tunnels down/flapping or partial secure-fabric/service/underlay failure.

Primary objective: isolate the failed circuit/path/tunnel rather than run a site-wide outage workflow blindly.

### `NETWORK_ANYNETLINK_DEGRADED`

Use as a **specific inter-site link/tunnel hint**. The SOP associates it with a single tunnel down/flapping and requires checking both endpoints.

Primary objective: identify the exact AnyNet link and its VPN legs, then correlate both endpoint underlays and leg status.

## Resolve entities with MCP

### Site

Use `find_site(name=...)` first when a human site name or exact site ID is known.

- Exact ID/name match is preferred by the MCP.
- If `ambiguous=true`, do not choose a candidate silently. Ask the user or refine with a more exact name/ID.

### Element / ION

If an element name/ID is known, use `find_element(name=...)`.

If only the site is known and the site's element names are not known, use `get_inventory(kind='elements', detail='summary')` and select records whose `site_id` equals the resolved site ID. Follow pagination if needed; do not assume the first page contains all site elements.

The SOP expects one or two devices per site, but the skill must not hard-code that assumption. Use the actual inventory.

## ID discipline

Do not collapse different identifier types.

- **site ID**: identifies a site.
- **element ID**: identifies an ION.
- **AnyNet `path_id`**: parent path identifier exposed by topology.
- **`anynet_link_id`**: controller AnyNet link identifier; MCP intentionally preserves it separately from `path_id`.
- **VPN leg ID**: child leg identifier from `vpnlinks`; required by `get_wan(operation='vpn_leg_status'|'vpn_leg_state', object_id=...)`.
- **WAN interface ID**: underlay interface identifier; can be correlated with `resolve_path` and topology/basenet output.

Never pass an AnyNet parent ID to an operation requiring a VPN leg ID.

## Topology workflow

### Site-centric problem

Use `get_topology(detail='summary', site=<site>)` to get a compact view of non-up links and status counts.

Use `get_topology(detail='full', site=<site>)` when exact endpoint names, AnyNet identifiers, circuit names, or VPN leg IDs are needed.

Use `get_topology(view='basenet', site=<site>)` when you need element/interface-level underlay mapping for VPN legs. Respect `next_leg_offset` if leg resolution is capped.

### Specific AnyNet problem

If the user supplies two endpoint sites, resolve both and inspect full topology for one endpoint, then match the peer endpoint and the supplied AnyNet identifier if present.

If only an AnyNet identifier is supplied and no endpoint is known, a tenant-wide topology summary can expose non-up links. If that is insufficient, use the MCP capability catalog/expert read path rather than guessing an endpoint.

### Two-endpoint rule

For `NETWORK_ANYNETLINK_DEGRADED` or a user-described point-to-point tunnel issue:

- investigate Site A and Site B separately;
- compare device reachability and relevant underlay at both ends;
- inspect the exact parent AnyNet link and its child VPN legs;
- report asymmetric evidence explicitly (for example, Site A underlay healthy while Site B circuit is failing).

Do not aggregate evidence so aggressively that endpoint-specific failure location is lost.

## Incident-time handling

If the user provides a timestamp, use it to create a narrow event window around the incident. A reasonable first window is several minutes before through several minutes after, widened only if evidence is sparse.

If no timestamp is provided:

- use recent state and recent events as clues;
- clearly state that a transient earlier cause may no longer be visible;
- ask for approximate incident time only if historical correlation becomes necessary.
