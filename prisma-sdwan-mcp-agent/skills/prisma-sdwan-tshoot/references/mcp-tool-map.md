# Prisma SD-WAN MCP Tool Map

Use semantic tools first. The MCP implementation, not this skill, owns authentication, API versions, retries, response redaction, and exact controller endpoints.

## Entity discovery

- `find_site` - resolve site name/ID; never auto-picks ambiguous matches.
- `find_element` - resolve ION name/serial/hardware ID/controller ID.
- `get_inventory` - enumerate sites/elements when names are not known.
- `resolve_path` - map an opaque path/interface/link ID without guessing.

## Device and interfaces

- `get_device_health` - combined element status, controller/config-events connection state, optional software/interfaces.
- `get_interfaces` - interface config and live operational state.

## WAN / topology / VPN

- `get_topology` - AnyNet topology; full or summary; `view='basenet'` derives VPN-leg endpoint/interface mapping.
- `get_wan(operation='interfaces')` - site WAN interfaces.
- `get_wan(operation='paths')` - site WAN paths.
- `get_wan(operation='vpn_leg_status')` - live operational status for one VPN leg ID.
- `get_wan(operation='vpn_leg_state')` - administrative state for one VPN leg ID.
- `get_wan(operation='vpn_links')` - tenant-wide VPN link records; do not treat it as site-filtered.

## Events and metrics

- `get_monitoring(operation='events'|'alarms')` - incident evidence; use explicit time windows for historical investigation.
- `get_monitoring(operation='link_metrics')` - recorded LQM/path telemetry and bandwidth.
- `get_monitoring(operation='probe_metrics')` - recorded synthetic probe telemetry.
- `get_monitoring(operation='flows')` - optional traffic/path correlation when the symptom is application/traffic-specific.

## Policies

- `get_policies(family='performance', ...)` - inspect configured performance policy where needed to determine whether observed quality actually violates configured policy.

## Expert escape hatch

Use `list_capabilities` then `read_capability` only when no semantic tool exposes required read-only evidence. Do not jump to the expert path just because the raw SOP listed an API endpoint.

Potentially useful expert reads for HA/site details include site/spoke-cluster status capabilities when semantic/CLI evidence is insufficient. Discover the exact action contract first rather than hard-coding an action blindly.

## ION CLI

`run_commands(commands=[...], element=<element>, site=<site>)` is the controlled device-side path.

Preferred read-only command families:

- `dump ...`
- `inspect ...`

Permitted active diagnostic forms include:

- `ping <interface> <host>`
- `tcpping <interface> <host>:<port>`
- `dig <interface> <dns-server> <hostname>`

Do not use unsupported SOP commands such as `nslookup`, `debug controller reachability`, or `file tailf ...` through `run_commands`.

## MCP error interpretation

Important `run_commands` distinction:

- `device_unreachable` means the MCP server deployment cannot reach the ION management address over its SSH path. This does not prove the Prisma production underlay or controller path is down.
- `host_key_unverified` is an SSH trust/setup issue.
- `device_authentication_failed` is an SSH credential/authorization issue.
- command-level `error` can coexist with successful sibling commands in a batch; inspect each result independently.
