# AI Tool Catalog

**Total: 27 tools.**

| Tool | Primary use |
|---|---|
| `find_site` | Safe site name/ID resolution |
| `find_element` | Safe ION/element name/ID resolution |
| `find_resource` | Resolve machine/app/zone/WAN network/path group/service label/VRF/policy |
| `list_capabilities` | Browse the full registry by domain, with exact method filtering |
| `read_capability` | Guarded expert execution of an exact read-only action_id |
| `resolve_path` | Map opaque path IDs to WAN interface/AnyNet/VPN leg |
| `get_inventory` | Sites, elements, machines, application definitions |
| `get_device_health` | Combined element/software/interface health |
| `get_interfaces` | Interface config/status/both |
| `get_topology` | AnyNet topology summary or bounded detail |
| `get_wan` | WAN interfaces/networks/paths/VPN links/VRFs/LAN/IPsec |
| `get_routing` | BGP, OSPF, static routes, route maps/lists |
| `get_device_diagnostics` | LLDP, MAC, VLAN mappings, BFD, app probes |
| `get_monitoring` | Events, alarms, flows, metrics, AIOps |
| `get_policies` | Network/priority/NAT/security/performance policy sets/stacks/rules/status |
| `get_security` | Zones, application definitions/version, NGFW prefixes, SD-WAN apps |
| `get_network_services` | DNS, DHCP, NTP, syslog, SNMP, TACACS+, RADIUS |
| `get_multicast` | Multicast config/RPs/routes/IGMP/WAN status |
| `get_ipfix` | IPFIX config/collectors/filters/templates/prefixes |
| `get_cellular` | Cellular modules/images/APNs/firmware state |
| `get_software` | Element software and upgrade/template status |
| `get_identity` | Directory/users/groups/active IPs/element users |
| `get_service_connections` | Service connections/endpoints/bindings/labels/extensions |
| `get_prisma_access` | Prisma Access/SASE/ADEM integration state |
| `get_platform` | Tenant/licenses/SKUs/machines/reports/platform metadata |
| `generate_site_config` | Local-only validated YAML generation for downstream automation |
| `run_commands` | Policy-approved ION CLI batch over SSH — `dump`/`inspect` plus `ping`/`tcpping`/`dig` (not read-only) |

## `run_commands`

The only tool that reaches the **device** rather than the controller API, and the only one not annotated read-only: `ping`/`tcpping`/`dig` send real packets from the ION. Everything else it permits (`dump`, `inspect`) is display-only.

- **Command selection is not this server's job.** Which `dump`/`inspect` subcommand answers a symptom is the calling agent's decision, driven by its own skill files. This tool only enforces which commands are *safe to run at all* — see the `prisma-cli://policy` resource for the exact allowed forms, generated from the same constants the validator evaluates.
- **Addressing:** pass `element` (resolved the same way every other tool resolves a name, via the shared resolver) or an explicit `host`. An explicit `host` always wins and is never second-guessed: when it is present nothing is resolved, and supplying `element` alongside it is allowed — the element then only labels the response. Name resolution prefers the interface whose `used_for` is `controller`, falling back to `lan`, and reads the live address from the interface status record so DHCP-assigned addresses resolve as well as static ones.
- **Credentials** come from `PRISMA_ION_USERNAME`/`PRISMA_ION_PASSWORD`/`PRISMA_ION_PRIVATE_KEY`/`PRISMA_ION_PRIVATE_KEY_PASSPHRASE`, not from a tool argument that would land in the transcript. Unset means the tool always fails closed with `configuration_error`, before any resolution or network call.
- **Error codes:** `policy_denied`, `configuration_error`, `device_unreachable` (no network path to the device — fails in seconds, not an auth or device problem), `host_key_unverified` (SSH host key not already in `known_hosts`), `device_authentication_failed`, `device_connection_failed`, plus the standard `not_found`/`ambiguous_match`/`invalid_argument` for addressing/input problems.
- **Per-command results are independent:** one command's device-side rejection doesn't invalidate its batch siblings, and each result declares its own truncation state.

## Why the expert tool exists

Some of the 308 registry actions will be rare or tenant-specific. Creating a dedicated MCP tool for each would make normal AI tool selection worse. `list_capabilities` + `read_capability` covers that long tail while keeping the normal surface understandable: `list_capabilities()` enumerates domains, `list_capabilities(domain=...)` lists every action in one, no text guessing involved.
