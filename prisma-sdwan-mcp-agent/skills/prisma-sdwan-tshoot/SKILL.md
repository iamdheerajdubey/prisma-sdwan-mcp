---
name: prisma-sdwan-tshoot
description: Troubleshoot Prisma SD-WAN site connectivity, AnyNet/VPN tunnel degradation, underlay failures, controller reachability, HA state, and path-quality problems using the Prisma SD-WAN MCP server. Use when a user reports a site down/degraded, tunnel or AnyNet link down/flapping, circuit/ISP failure, controller disconnect, packet loss, latency, jitter, SLA degradation, or provides Prisma alert text such as SITE_CONNECTIVITY_DOWN, SITE_CONNECTIVITY_DEGRADED, or NETWORK_ANYNETLINK_DEGRADED. Diagnose from free-form user/event descriptions; do not perform ITSM ticket loading or updates.
---

# Prisma SD-WAN Troubleshooting

## Goal

Diagnose Prisma SD-WAN connectivity and performance problems from the user's symptom or event description. Use the MCP server for evidence collection. Converge on the most specific fault domain supported by evidence; do not mechanically replay a fixed runbook.

## Core operating rules

1. Start from the reported symptom and affected scope, not from a predetermined Step 1/2/3 sequence.
2. Treat alert type as context, not as proof of root cause.
3. Resolve human names to controller IDs before deeper checks. Never silently choose an ambiguous site or element.
4. Prefer semantic MCP tools and controller evidence before raw ION CLI.
5. Use raw CLI only when it distinguishes remaining hypotheses or supplies evidence unavailable from semantic tools.
6. Do not run every check. Every tool call must establish scope, validate/eliminate a hypothesis, or provide evidence required for the next decision.
7. Correlate both endpoints for a point-to-point AnyNet/VPN problem whenever possible.
8. Keep these IDs distinct: site ID, element ID, AnyNet `path_id`, controller `anynet_link_id`, VPN leg ID, WAN interface ID. Never substitute one for another.
9. Use explicit incident time windows for historical events when the user provides an event time. Unwindowed event queries can miss older incidents.
10. Distinguish controller-recorded telemetry from current active diagnostics. Recorded LQM/probe metrics are not proof that a symptom still exists now.
11. Treat `run_commands` `device_unreachable` as an MCP-to-ION management-path limitation, not evidence that the production site itself is down.
12. Never invent a root cause, SLA threshold, topology mapping, tunnel reason, or user intent.
13. Do not change configuration. This troubleshooting skill is diagnostic. Recommend changes only after identifying evidence and impact.
14. Do not load from or write to ITSM/ServiceNow. The AI conversation is the interface.

## Diagnostic loop

Use this loop until a conclusion is justified:

1. **Normalize the symptom** - identify affected site(s), device(s), circuit/path, tunnel, direction, impact, alert type if present, and incident time if present.
2. **Establish scope** - determine whether the problem is site-wide, device-specific, circuit-specific, tunnel-specific, or quality-only.
3. **Form a small hypothesis set** - normally choose from device/power/HA, underlay L1/L2/L3, controller/control-plane, overlay/VPN, or path quality.
4. **Choose the highest-value next check** - favor evidence that separates multiple hypotheses at once.
5. **Collect and correlate evidence** - compare both HA members, WAN paths, both tunnel endpoints, event timestamps, topology state, and live/recorded metrics as applicable.
6. **Prune hypotheses** - explicitly discard causes contradicted by evidence.
7. **Stop when sufficient** - once one fault domain is strongly supported and further checks would not change the recommended action, stop.
8. **If insufficient** - state what is confirmed, what remains possible, and the single most useful next evidence to collect.

## Initial routing

Read only the references relevant to the current investigation:

- For alert semantics, free-form input normalization, entity resolution, endpoint handling, and ID semantics: read `references/scope-and-topology.md`.
- For disconnected IONs, power suspicion, active/standby identification, HA peer loss, or split brain: read `references/device-reachability-ha.md`.
- For WAN circuit, interface, ARP, ISP, DNS, internet reachability, or controller reachability: read `references/underlay-controller.md`.
- For AnyNet/VPN tunnel down/degraded/flapping, VPN leg state, BFD, key synchronization, or admin-down cases: read `references/overlay-tunnels.md`.
- For packet loss, latency, jitter, MOS, poor performance, or SLA/path-quality warnings: read `references/path-quality.md`.
- For known event/CLI signatures and how strongly they support a diagnosis: read `references/failure-signatures.md`.
- Before presenting the final diagnosis: read `references/conclusion-format.md`.
- When uncertain which MCP capability matches the diagnostic need: read `references/mcp-tool-map.md`.

## Default investigation priorities

Apply these priorities unless the symptom strongly points elsewhere:

### Complete site outage

1. Resolve site and enumerate its IONs.
2. Determine whether zero, one, or multiple IONs are controller-connected.
3. If all IONs are disconnected, inspect time-correlated site/device alarms before attempting CLI.
4. If an ION is reachable, identify the active HA member if HA is configured.
5. Evaluate active WAN interfaces and underlay reachability.
6. If underlay works, evaluate controller/control-plane connectivity.
7. Evaluate overlay only after the local device and underlay are credible.

### Partial site degradation

1. Identify which WAN path/circuit or tunnel is affected instead of treating the whole site as failed.
2. Confirm interface state and path mapping.
3. Separate physical/L2/L3 underlay failure from overlay failure.
4. If links and tunnels are up, evaluate path quality and configured performance policy before declaring an SLA breach.

### AnyNet/VPN link degradation

1. Resolve both endpoints and the exact AnyNet link.
2. Keep AnyNet parent identifiers separate from VPN leg IDs.
3. Inspect both endpoint underlays and live VPN leg status/state.
4. If a leg is down, determine whether it is administratively disabled, underlay-impaired, BFD/liveliness-impaired, key/control-plane-impaired, or unknown.
5. Do not diagnose the local ISP from a remote tunnel symptom without underlay evidence.

## Evidence hierarchy

Prefer, in order:

1. Exact controller state tied to the affected entity and incident time.
2. Correlated state from both sides of the same path/tunnel.
3. Read-only current ION state (`dump`/`inspect`).
4. Narrow active diagnostics (`ping`, `tcpping`, `dig`) when needed.
5. Inference only after the above evidence is evaluated.

An event name alone is a clue. A current state alone can miss a transient incident. Strong conclusions usually combine timestamped history with current state.

## Safety and CLI policy

`run_commands` permits the `dump` and `inspect` families plus narrowly allowed `ping`, `tcpping`, and `dig` forms. It denies other command families by default. Do not work around the MCP policy.

Important SOP adaptations:

- Do not use `debug controller reachability`; the MCP deliberately denies it. Use controller status from `get_device_health` plus DNS/TCP checks when necessary.
- Do not use `file tailf log ham`; it is outside the allowed CLI policy. Use HA status/config, controller events, and other permitted evidence.
- Prefer `get_monitoring(operation='link_metrics')` for recorded path quality and `inspect lqm stats internet` only as a current supplemental device snapshot.

## Interaction with the user

Ask a clarification only when a required entity is genuinely ambiguous or a missing fact blocks safe interpretation. Do not ask for data MCP can retrieve itself.

If the user's description has no alert type, proceed symptom-first. If it includes one of the SOP alert types, use it to set scope but verify the actual state.

## Stop conditions

Stop deeper probing when any of the following is true:

- A high-confidence fault domain is established and additional checks would not change the recommended action.
- The next required evidence is unavailable through the current MCP/CLI access path.
- The remaining action requires human context not available to the agent, such as why an interface/tunnel was intentionally administratively disabled.
- Entity resolution remains ambiguous after available lookup evidence; ask the user to select the exact entity.

Never present "unknown" as a root cause. Present it as insufficient evidence with the next best check.
