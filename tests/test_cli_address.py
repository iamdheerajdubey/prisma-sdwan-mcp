"""Address resolution tests.

Fixtures mirror the payloads a real ion 5200 returned (see
docs/LIVE_VALIDATION.md): DHCP interfaces carry no address in their config
record, `admin_up` is true even on physically down ports, and the live
address for every interface lives in the status record.
"""

import pytest

import prisma_sdwan_mcp.cli.address as address
from prisma_sdwan_mcp.resolver import ResolutionError


def _patch_site_element(monkeypatch, site_id="site1", element_id="elem1", record=None):
    record = record if record is not None else {"id": element_id, "name": "IMEMION1", "site_id": site_id}
    monkeypatch.setattr(address, "site_element", lambda site, element: (site_id, element_id, record))


def _patch_execute(monkeypatch, interfaces, statuses, calls=None):
    """statuses: interface_id -> {"ipv4_addresses": [...], "operational_state": ...}"""

    def fake_execute(action_id, paths=None, body=None):
        if calls is not None:
            calls.append((action_id, (paths or {}).get("interface_id")))
        if action_id == "sites_devices.interfaces":
            return {"items": interfaces}
        if action_id == "sites_devices.interfaces_status":
            return statuses.get(paths["interface_id"], {})
        raise AssertionError(f"unexpected action_id {action_id}")

    monkeypatch.setattr(address, "execute", fake_execute)


# The shape the live device actually returns, trimmed to the fields used.
REAL_INTERFACES = [
    {"id": "if17", "name": "17", "used_for": "controller", "admin_up": True,
     "ipv4_config": {"type": "static", "static_config": {"address": "10.175.10.101/24"}}},
    {"id": "if1", "name": "1", "used_for": "public", "admin_up": True,
     "ipv4_config": {"type": "dhcp"}},
    {"id": "if19", "name": "19", "used_for": "lan", "admin_up": True,
     "ipv4_config": {"type": "static", "static_config": {"address": "10.175.202.1/24"}}},
    {"id": "ifvi99", "name": "VI.99", "used_for": "lan", "admin_up": True,
     "ipv4_config": {"type": "static", "static_config": {"address": "10.175.0.37/27"}}},
    {"id": "ifvi15", "name": "VI.15", "used_for": "ha", "admin_up": True,
     "ipv4_config": {"type": "static", "static_config": {"address": "10.175.15.11/24"}}},
    {"id": "ifsl1", "name": "MEMPHIS_HQ_INTERNET1_ACT_SL", "used_for": "none", "admin_up": True,
     "ipv4_config": {"type": "static", "static_config": {"address": "172.16.1.0/31"}}},
]

REAL_STATUSES = {
    "if17": {"ipv4_addresses": ["10.175.10.101/24"], "operational_state": "up"},
    "if1": {"ipv4_addresses": ["166.155.138.190/30"], "operational_state": "up"},
    "if19": {"ipv4_addresses": ["10.175.202.1/24"], "operational_state": "down"},
    "ifvi99": {"ipv4_addresses": ["10.175.0.37/27"], "operational_state": "up"},
}


def test_controller_role_wins_on_the_real_device_shape(monkeypatch):
    calls = []
    _patch_site_element(monkeypatch)
    _patch_execute(monkeypatch, REAL_INTERFACES, REAL_STATUSES, calls)

    result = address.resolve_device_address("IMEMION1")

    assert result == {
        "host": "10.175.10.101",
        "element_id": "elem1",
        "element_name": "IMEMION1",
        "site_id": "site1",
        "interface_id": "if17",
        "interface_name": "17",
        "used_for": "controller",
    }
    # Only the one controller-role interface needed a status call: the lan,
    # ha, public and service-link interfaces were never touched.
    assert calls == [("sites_devices.interfaces", None), ("sites_devices.interfaces_status", "if17")]


def test_dhcp_address_is_read_from_status_not_config(monkeypatch):
    """The DHCP interface has no config address; the status record has the live one."""
    _patch_site_element(monkeypatch)
    interfaces = [{"id": "ifd", "name": "1", "used_for": "controller", "admin_up": True, "ipv4_config": {"type": "dhcp"}}]
    _patch_execute(monkeypatch, interfaces, {"ifd": {"ipv4_addresses": ["166.155.138.190/30"], "operational_state": "up"}})

    result = address.resolve_device_address("IMEMION1")

    assert result["host"] == "166.155.138.190"


def test_lan_is_used_when_no_controller_role_exists(monkeypatch):
    _patch_site_element(monkeypatch)
    interfaces = [i for i in REAL_INTERFACES if i["used_for"] != "controller"]
    _patch_execute(monkeypatch, interfaces, REAL_STATUSES)

    result = address.resolve_device_address("IMEMION1")

    # if19 is admin_up but operationally down, so VI.99 is the only live lan.
    assert result["host"] == "10.175.0.37"
    assert result["used_for"] == "lan"


def test_operationally_down_interface_is_not_a_candidate(monkeypatch):
    _patch_site_element(monkeypatch)
    interfaces = [{"id": "if19", "name": "19", "used_for": "controller", "admin_up": True,
                   "ipv4_config": {"type": "static", "static_config": {"address": "10.175.202.1/24"}}}]
    _patch_execute(monkeypatch, interfaces, {"if19": {"ipv4_addresses": ["10.175.202.1/24"], "operational_state": "down"}})

    with pytest.raises(ResolutionError) as exc:
        address.resolve_device_address("IMEMION1")

    assert "no live management address" in str(exc.value)
    # The rejected interface is still reported so the operator can see why.
    assert exc.value.candidates[0]["operational_state"] == "down"


def test_two_live_controller_addresses_return_candidates(monkeypatch):
    _patch_site_element(monkeypatch)
    interfaces = [
        {"id": "ifa", "name": "17", "used_for": "controller", "admin_up": True, "ipv4_config": None},
        {"id": "ifb", "name": "18", "used_for": "controller", "admin_up": True, "ipv4_config": None},
    ]
    statuses = {
        "ifa": {"ipv4_addresses": ["10.0.0.5/24"], "operational_state": "up"},
        "ifb": {"ipv4_addresses": ["10.0.0.6/24"], "operational_state": "up"},
    }
    _patch_execute(monkeypatch, interfaces, statuses)

    with pytest.raises(ResolutionError) as exc:
        address.resolve_device_address("IMEMION1")

    assert len(exc.value.candidates) == 2
    assert {c["address"] for c in exc.value.candidates} == {"10.0.0.5", "10.0.0.6"}


def test_ambiguous_controller_does_not_silently_fall_through_to_lan(monkeypatch):
    """A tie inside the preferred role is an error, not a reason to try the next one."""
    _patch_site_element(monkeypatch)
    interfaces = [
        {"id": "ifa", "name": "17", "used_for": "controller", "admin_up": True, "ipv4_config": None},
        {"id": "ifb", "name": "18", "used_for": "controller", "admin_up": True, "ipv4_config": None},
        {"id": "iflan", "name": "19", "used_for": "lan", "admin_up": True, "ipv4_config": None},
    ]
    statuses = {
        "ifa": {"ipv4_addresses": ["10.0.0.5/24"], "operational_state": "up"},
        "ifb": {"ipv4_addresses": ["10.0.0.6/24"], "operational_state": "up"},
        "iflan": {"ipv4_addresses": ["10.9.9.9/24"], "operational_state": "up"},
    }
    _patch_execute(monkeypatch, interfaces, statuses)

    with pytest.raises(ResolutionError) as exc:
        address.resolve_device_address("IMEMION1")

    assert all(c["used_for"] == "controller" for c in exc.value.candidates)


def test_no_management_role_interface_is_an_error(monkeypatch):
    _patch_site_element(monkeypatch)
    interfaces = [i for i in REAL_INTERFACES if i["used_for"] in ("public", "ha", "none")]
    _patch_execute(monkeypatch, interfaces, REAL_STATUSES)

    with pytest.raises(ResolutionError) as exc:
        address.resolve_device_address("IMEMION1")

    assert exc.value.candidates == []


def test_status_returned_as_a_list_is_handled(monkeypatch):
    _patch_site_element(monkeypatch)
    interfaces = [{"id": "if17", "name": "17", "used_for": "controller", "admin_up": True, "ipv4_config": None}]
    _patch_execute(monkeypatch, interfaces, {"if17": [{"ipv4_addresses": ["10.175.10.101/24"], "operational_state": "up"}]})

    assert address.resolve_device_address("IMEMION1")["host"] == "10.175.10.101"


def test_unresolvable_element_name_is_a_distinct_error(monkeypatch):
    monkeypatch.setattr(address, "site_element", lambda site, element: (None, None, None))

    with pytest.raises(ResolutionError):
        address.resolve_device_address("no-such-element")
