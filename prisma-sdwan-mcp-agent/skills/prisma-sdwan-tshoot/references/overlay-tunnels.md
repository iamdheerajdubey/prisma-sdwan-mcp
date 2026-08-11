# Overlay / AnyNet / VPN Tunnel Troubleshooting

## Contents

- Identify the exact AnyNet link
- Inspect VPN-leg status/state
- Correlate underlay
- CLI deep diagnostics
- Administrative/key/BFD/unknown decision logic
- Both-endpoint reasoning

## Goal

When the device and relevant underlay are credible, isolate an overlay failure to the exact AnyNet parent link and VPN leg, then distinguish administrative, underlay, liveliness/BFD, key/control-plane, or unknown causes.

## 1. Identify the exact affected link

Use `get_topology(detail='full', site=<site>)`.

Match using all available evidence:

- peer site;
- `anynet_link_id` when supplied;
- `path_id` when supplied;
- source/target circuit names;
- status;
- child `vpnlinks` IDs.

For `NETWORK_ANYNETLINK_DEGRADED`, do not troubleshoot every down VPN in the tenant. Isolate the exact inter-site link first.

Use `get_topology(view='basenet', site=<site>)` when you need element/interface mapping for child VPN legs.

## 2. Inspect live controller VPN-leg state

For each suspect VPN leg ID:

- `get_wan(operation='vpn_leg_status', object_id=<vpn-leg-id>)`
- `get_wan(operation='vpn_leg_state', object_id=<vpn-leg-id>)`

These calls distinguish live operational status from administrative state without depending on CLI text parsing.

Never pass the AnyNet parent `path_id` as the VPN leg `object_id`.

## 3. Correlate the underlay before blaming overlay

For each endpoint/leg:

- map the leg to endpoint element/interface using basenet/topology data;
- confirm relevant interface state;
- confirm underlay reachability when needed.

If the exact circuit is down or unusable, classify the tunnel loss as a consequence of underlay failure. Do not over-diagnose BFD/crypto merely because the tunnel is down.

## 4. Use ION CLI for deeper failure semantics when needed

Permitted read-only examples:

- `dump vpn summary all`
- `dump vpn status VpnID=<vep-or-vpn-id-as-device-expects>`
- `dump vpn ka VpnID=<vep-or-vpn-id-as-device-expects>`

Use the ID format actually shown by the device/topology and do not assume controller AnyNet IDs equal CLI VepIDs.

Extract only evidence actually present, such as:

- administrative state (`admin_up`);
- operational status;
- reason text;
- local/remote tunnel addresses;
- link healthy/liveliness indications;
- keepalive/BFD counters/state.

## 5. Decision logic

### Administratively disabled

Evidence examples:

- `admin_up=false`;
- reason contains "Administratively Down";
- controller administrative state reports disabled.

Conclusion: tunnel is administratively disabled, not an unexplained transport outage.

Do not claim human error. The agent lacks the change context needed to know whether the disablement was intentional. Recommend reviewing the intended configuration/change history.

### Shared-secret/key synchronization indication

If device reason text explicitly indicates loss/out-of-sync shared secret or equivalent key synchronization failure:

1. confirm basic underlay and controller transport are not failing;
2. collect `dump time status` to check clock state;
3. collect current VPN status/keepalive evidence;
4. review controller events around the failure;
5. report key/control-plane synchronization as the likely fault domain, with the exact reason text paraphrased.

Do not assert clock drift caused it unless time evidence supports that.

### BFD failure

If the device explicitly reports `BFD Failure`:

1. confirm the relevant underlay interface/path is not hard down;
2. inspect `dump vpn ka ...` and current VPN status;
3. inspect path-quality evidence if loss/jitter could explain liveliness drops;
4. correlate both endpoints.

If underlay is healthy but BFD is failing, isolate the problem to overlay liveliness/quality rather than local L1/L2.

### Reason N/A / unknown / unclassified

`N/A` is not a root cause.

Collect the smallest useful additional set:

- VPN status;
- VPN keepalive;
- endpoint underlay mapping/status;
- time-correlated events;
- path quality when symptoms suggest loss/jitter.

If evidence remains non-specific, return **insufficient evidence** and identify the next missing signal. Do not label "complex issue" as a diagnosis.

## 6. Both-endpoint reasoning

For a point-to-point degradation, prefer a matrix like:

| Evidence | Endpoint A | Endpoint B |
|---|---|---|
| ION/controller reachability | observed | observed |
| Underlay interface | observed | observed |
| Internet/MPLS reachability | observed | observed |
| VPN leg admin state | observed | observed |
| VPN leg operational state/reason | observed | observed |
| Path quality | if relevant | if relevant |

Use asymmetry to locate the fault. Example: A underlay healthy + B physical circuit down + shared tunnel down supports Endpoint B underlay as the causal fault domain.
