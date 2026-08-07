# AI Tool Catalog

**Total: 26 tools.**

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

## Why the expert tool exists

Some of the 308 registry actions will be rare or tenant-specific. Creating a dedicated MCP tool for each would make normal AI tool selection worse. `list_capabilities` + `read_capability` covers that long tail while keeping the normal surface understandable: `list_capabilities()` enumerates domains, `list_capabilities(domain=...)` lists every action in one, no text guessing involved.
