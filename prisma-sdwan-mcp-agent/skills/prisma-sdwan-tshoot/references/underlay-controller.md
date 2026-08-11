# Underlay and Controller Reachability

## Contents

- WAN/path identification
- Layer 1 interface state
- Layer 2 gateway adjacency
- Layer 3 underlay reachability
- DNS
- Controller/control-plane reachability
- Health-probe false positives

## Goal

Separate physical/interface, Layer-2/gateway, Layer-3/ISP, DNS, and controller/TCP reachability faults.

## Start with the affected WAN path

Prefer controller/API mapping before raw CLI:

- `get_wan(operation='interfaces', site=<site>)` for WAN interface inventory.
- `get_wan(operation='paths', site=<site>)` for WAN path state/configuration.
- `get_topology(view='basenet', site=<site>)` and `resolve_path(site=<site>, path_id=<id>)` for path-to-interface/tunnel correlation.

Use `dump waninterface config` when API mapping is incomplete or current device-local detail is required.

Do not test every WAN interface if topology already identifies the specific affected path. For site-wide outage, evaluate all interfaces that can provide controller/overlay reachability.

## Layer 1 - interface operational state

Preferred semantic tool:

- `get_interfaces(element=<active-ion>, site=<site>, mode='both', interface=<target>)`

CLI fallback/detail:

- `dump interface status <interface>`

Interpretation:

- administratively disabled: human/configuration intent may be involved; do not re-enable or infer why it was disabled;
- operational/link down: local physical handoff, SFP/cabling, ISP CPE/access circuit, or upstream port are likely fault domains;
- link up: continue to L2/L3. Link-up does not prove usable service.

Do not state "ISP is down" solely from physical link down. The failure is at or beyond the WAN handoff; exact ownership needs circuit context.

## Layer 2 - gateway adjacency

When the interface is link-up and the gateway/route is known, inspect ARP:

- `inspect system arp interface=<interface> | grep ether`

If expected gateway ARP is missing/incomplete while the interface is up, strongly suspect the local L2 path between the ION and upstream gateway (ISP CPE, switch, VLAN/handoff, or provider access).

Do not require ARP checks for interfaces/path types where an ARP gateway is not applicable.

## Layer 3 - underlay reachability

Use narrow active diagnostics only after interface mapping is clear.

The SOP uses multiple public probe destinations. Useful examples are:

- `ping <interface> 8.8.8.8`
- `ping <interface> 8.8.4.4`
- `ping <interface> 208.67.222.222`
- `ping <interface> 208.67.220.220`

Do not run all four automatically. Start with one or two independent targets; expand only if a destination-specific false negative is plausible.

Interpretation:

- link up + gateway ARP present + repeated independent public probe failures strongly supports an upstream/ISP routing/reachability problem;
- one public host failing while others succeed is not enough to blame the ISP;
- active ping success shows current IP reachability, not historical health at the incident time.

## DNS

The SOP uses `nslookup`, but the MCP CLI policy does not permit it. Use the permitted exact diagnostic form instead:

- `dig <interface> <dns-server> <hostname>`

Obtain the configured DNS server from interface/device configuration; do not invent one. Use a Prisma controller hostname relevant to the environment when testing controller-name resolution.

If IP reachability is healthy but DNS resolution fails using the configured resolver, classify DNS/config/upstream resolver as the likely fault domain.

## Controller/control-plane reachability

Do not use `debug controller reachability`; the MCP intentionally denies it.

Use two evidence sources:

### Controller-recorded state

`get_device_health` exposes element operational status including controller/config-and-events connection fields when the API supplies them. These are primary control-plane evidence.

### Device-originated TCP test

When DNS resolves and current path testing is needed:

- `tcpping <interface> <controller-host>:443`

Interpretation:

- internet/IP reachability works + DNS works + TCP/443 fails: suspect upstream filtering/firewall/NAT/path handling before declaring the controller itself down;
- TCP/443 succeeds but controller status remains disconnected: investigate control/session/auth/time synchronization evidence rather than blaming basic transport;
- controller-recorded state is healthy and the site symptom is tunnel-specific: move to overlay diagnostics.

## Captive/health-probe false-positive checks

If the platform relies on mandatory internet reachability probes and the interface is otherwise usable, the SOP checks ICMP and TCP endpoints such as captive.apple.com and clients3.google.com.

Use these only when you are testing the hypothesis that health probes are blocked while general internet service works. Do not make them a mandatory step in every investigation.

Permitted examples:

- `tcpping <interface> captive.apple.com:80`
- `tcpping <interface> clients3.google.com:80`

If these fail but other internet/control traffic works, report a health-probe-specific reachability issue rather than "ISP down".
