# Device Reachability and HA

## Goal

Determine whether the failure is at the ION/device/power/HA layer before spending effort on tunnels.

## 1. Determine controller-visible device reachability

For every ION at the affected site:

1. Use inventory to identify the element and `connected` state.
2. Use `get_device_health(element=<element>, site=<site>, include_software=false)` for operational detail.
3. Pay attention to `element_status` fields such as controller/config-and-events connectivity when present.

Classify the site for this investigation:

- **NO_ION_REACHABLE** - no site ION is controller-connected.
- **SOME_ION_REACHABLE** - at least one is connected, at least one is not.
- **ALL_ION_REACHABLE** - all discovered IONs are connected.

Do not equate `run_commands` management SSH reachability with controller connectivity. They are different network paths.

## 2. No ION reachable

Do not attempt device CLI first. Query time-correlated evidence through the controller:

- `get_monitoring(operation='alarms', site=<site>, start_time=..., end_time=...)`
- `get_monitoring(operation='events', site=<site>, start_time=..., end_time=...)`

If only recent data is needed and no incident time exists, use recent alarms/events but state the historical limitation.

High-value signatures:

- `DEVICEHW_POWER_LOST` immediately preceding disconnect strongly supports power/device-power loss.
- `NETWORK_DIRECTINTERNET_DOWN` on all active internet circuits near the same time supports a common underlay/ISP/access failure.
- interface-down events on all usable WAN interfaces support local access/physical/circuit failure.

If all devices are disconnected and none of these signatures exist, do not label "hardware failure" simply because it is on the SOP suspect list. Report device/site unreachable and the last relevant event evidence; hardware failure remains a hypothesis unless independently supported.

## 3. At least one ION reachable

Determine active/standby state only when HA is configured or inventory indicates multiple HA members.

Preferred evidence sequence:

1. Use controller inventory/health to understand which devices are connected.
2. If more HA detail is needed and SSH is available, run permitted read-only commands on each reachable ION:
   - `dump spoke-ha status`
   - `dump spoke-ha config` when configuration context is needed.

Interpret key fields from `dump spoke-ha status`:

- `Active: true` identifies the active device at that instant.
- `Peer Connected: true` indicates HA peer connectivity.

## 4. HA exception logic

### Peer disconnected

If both reachable members report peer not connected, classify as **HA peer/link instability** unless other evidence shows one peer itself is down.

Do not stop automatically if the original symptom is WAN/tunnel degradation; continue using the reachable active member but include HA instability as a concurrent finding.

### Both devices report active

Treat as a **split-brain indicator**. Gather both members' `dump spoke-ha status` and `dump spoke-ha config` output and controller events around the transition.

The original SOP suggests `file tailf log ham`; do not use it because the MCP CLI policy does not permit the `file` family. Do not attempt to bypass policy.

### Only one device reachable

Use the reachable device for further diagnostics, but preserve the peer-unreachable finding. Do not assume the reachable device is healthy merely because it accepts SSH or appears controller-connected.

## 5. When to stop at this layer

A high-confidence device/power diagnosis is enough when:

- all IONs are unavailable;
- a directly relevant power/device event aligns with the outage time;
- no contradictory evidence suggests the event was transient and recovered before the user-reported impact.

Otherwise continue to underlay/controller checks on a reachable device.
