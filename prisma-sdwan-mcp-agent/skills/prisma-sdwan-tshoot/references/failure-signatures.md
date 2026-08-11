# Failure Signatures and Evidence Strength

Use this reference to interpret common Prisma SD-WAN signals. A signature is evidence, not a complete diagnosis by itself.

## Device / site

### `DEVICEHW_POWER_LOST`

Strongly supports device power loss when it occurs immediately before the affected ION disconnects. Confidence rises if all site IONs show aligned power/disconnect evidence.

Do not generalize one device's power event to a whole-site power outage if another site device remained healthy.

### All site IONs `connected=false`

Supports controller-unreachable/device-unavailable state. It does not by itself distinguish power, WAN loss, controller transport failure, or hardware failure.

## Underlay

### `NETWORK_DIRECTINTERNET_DOWN`

Supports direct-internet path failure. Correlate with interface state and other circuits before deciding whether the site lost all underlays.

### Physical/interface operational down

Supports L1/handoff/access failure. It does not prove the provider core is down and may also reflect local cabling, SFP, CPE, or upstream switch state.

### Interface up + expected gateway ARP missing

Strongly supports L2 adjacency/handoff failure between ION and upstream gateway.

### Interface up + ARP present + multiple independent IP probes fail

Supports upstream L3/ISP reachability failure, assuming source/interface mapping is correct.

### Internet probes succeed + DNS fails via configured resolver

Supports DNS/resolver/configuration fault rather than broad internet loss.

### Internet + DNS work + TCP/443 controller test fails

Supports upstream filtering/firewall/NAT/path issue toward the controller service. Confirm controller hostname/port and controller-recorded status before narrowing further.

## HA

### `Active: true` on exactly one HA member

Normal active/standby indication at the observation time.

### `Peer Connected: false` on both reachable members

Supports HA peer-link/peer-connectivity fault. Continue original service troubleshooting because HA instability can coexist with a WAN fault.

### `Active: true` on both members

Strong split-brain indicator. Correlate time and controller events.

## Overlay / VPN

### `admin_up=false` / "Administratively Down"

Strong evidence of administrative disablement. Do not label it accidental/human error without change context.

### shared-secret/key out-of-sync reason

Supports crypto/key/control-plane synchronization failure. Clock drift is only one hypothesis; verify with `dump time status` before attributing cause.

### `BFD Failure`

Supports overlay liveliness failure. If underlay/path quality is bad, the BFD failure may be downstream evidence of underlay quality. If underlay is healthy, the fault is more isolated to overlay/BFD/control behavior.

### Reason `N/A`

No useful root-cause evidence. Never report `N/A` or "complex issue" as the diagnosis.

## Path quality

### Elevated loss/jitter/latency or poor MOS

Supports a quality impairment on the measured path and time window. It does not prove SLA breach until compared with the configured policy/profile.

### Recorded metric healthy but live user symptom persists

Possible metric lag, wrong path mapping, intermittent issue, or a problem outside measured path quality. Use a current permitted diagnostic only if it can discriminate those possibilities.

## Confidence scale

Use a simple evidence-based scale:

- **High** - multiple independent signals point to the same fault domain and major alternatives are contradicted.
- **Medium** - evidence is consistent and reasonably specific, but one or more meaningful alternatives remain.
- **Low** - evidence is weak, indirect, stale, unmapped, or incomplete.

Do not assign numeric percentages unless the system explicitly provides a calibrated model for them.
