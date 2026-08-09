"""Element name -> SSH-reachable address, entirely through the registry.

No endpoint path is hard-coded here: every controller fact comes from
`tools/common.py`'s `execute()` (registry action IDs) and `site_element()`
(the existing resolver).

This runs only when the caller names an element. An explicit `host` bypasses
this module entirely and is never second-guessed.

Shaped by a live read against a real ion 5200 (see docs/LIVE_VALIDATION.md):

- An interface's *configured* address exists only when `ipv4_config.type` is
  `static`. A DHCP interface carries no address in its config record at all.
  The live address for **both** kinds is in `sites_devices.interfaces_status`
  as `ipv4_addresses`, so that is the only source read here.
- `admin_up` is true on nearly every interface including ones that are
  physically down, so it is not a liveness signal. `operational_state` from
  the status record is.
- `used_for` is the field that separates a management address from noise. On
  the sampled device, filtering to `controller`/`lan` cut 16 candidates to 3,
  and preferring `controller` left exactly one.
- `element_status.controller_connection_intf` is deliberately NOT used as the
  tie-breaker: on the sampled device it pointed at the DHCP public WAN port
  the device happens to reach the cloud through, which is the wrong target
  for an SSH management session.
"""

from __future__ import annotations

from typing import Any

from ..resolver import ResolutionError
from ..tools.common import execute, records, site_element

# Most preferred first. An interface serving any other purpose -- a public WAN
# port, an HA link, a service-link tunnel endpoint -- is not a management
# address and is never a candidate.
MANAGEMENT_ROLES = ("controller", "lan")


def _live_addresses(site_id: str, element_id: str, interface_id: str) -> tuple[list[str], str | None]:
    """Return (addresses, operational_state) from the interface's status record."""
    status = execute(
        "sites_devices.interfaces_status",
        {"site_id": site_id, "element_id": element_id, "interface_id": interface_id},
    )
    if isinstance(status, list):
        status = status[0] if status else {}
    if not isinstance(status, dict):
        return [], None
    addresses = status.get("ipv4_addresses")
    if not isinstance(addresses, list):
        addresses = []
    return [str(a).split("/")[0] for a in addresses if a], status.get("operational_state")


def resolve_device_address(element: str, site: str | None = None) -> dict[str, Any]:
    """Resolve an element name to exactly one SSH address, or raise ResolutionError.

    Never guesses between candidates: a `ResolutionError` carries the candidate
    list whenever a role yields more than one live address, or no role yields
    any, mirroring the resolver's existing ambiguity contract.
    """
    site_id, element_id, element_record = site_element(site, element)
    if not element_id:
        raise ResolutionError(f"No element matches '{element}'")

    interfaces = records(execute("sites_devices.interfaces", {"site_id": site_id, "element_id": element_id}))

    # Status is fetched only for interfaces in a management role -- on the
    # sampled device that is 3 calls instead of 33.
    seen: list[dict[str, Any]] = []
    for role in MANAGEMENT_ROLES:
        candidates: list[dict[str, Any]] = []
        for interface in interfaces:
            if interface.get("used_for") != role:
                continue
            addresses, operational_state = _live_addresses(site_id, element_id, interface.get("id"))
            for address in addresses:
                candidate = {
                    "interface_id": interface.get("id"),
                    "interface_name": interface.get("name"),
                    "used_for": role,
                    "address": address,
                    "operational_state": operational_state,
                }
                seen.append(candidate)
                if operational_state == "up":
                    candidates.append(candidate)
        if len(candidates) == 1:
            chosen = candidates[0]
            return {
                "host": chosen["address"],
                "element_id": element_id,
                "element_name": (element_record or {}).get("name"),
                "site_id": site_id,
                "interface_id": chosen["interface_id"],
                "interface_name": chosen["interface_name"],
                "used_for": role,
            }
        if candidates:
            raise ResolutionError(
                f"{len(candidates)} live '{role}' addresses found for element '{element}'; "
                "specify host explicitly to choose one",
                candidates=candidates,
            )

    raise ResolutionError(
        f"no live management address found for element '{element}' "
        f"(looked at interfaces with used_for in {list(MANAGEMENT_ROLES)}); specify host explicitly",
        candidates=seen,
    )
