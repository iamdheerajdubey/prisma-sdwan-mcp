import json
from types import SimpleNamespace

import pytest

from prisma_sdwan_mcp import registry
from prisma_sdwan_mcp.tools.resolve import (
    FIND_CAP,
    find_app,
    find_element,
    find_machine,
    find_path_group,
    find_policy_set,
    find_security_zone,
    find_service_label,
    find_site,
    find_wan_network,
    resolve_path,
)


class FakeClient:
    def __init__(self, get=None, post=None):
        self.calls = []
        self.sdk = SimpleNamespace(
            get=SimpleNamespace(**(get or {})),
            post=SimpleNamespace(**(post or {})),
        )

    def call_sdk(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return function(*args, **kwargs)

    def call_sdk_post(self, function, data, **kwargs):
        self.calls.append((function, (data,), kwargs))
        return function(data, **kwargs)


SITES = [
    {"id": "site-1", "name": "AZURE AMSTERDAM", "display_name": "AMS Hub"},
    {"id": "site-2", "name": "AZURE LONDON", "display_name": "LON Hub"},
    {"id": "site-3", "name": "AWS FRANKFURT", "display_name": "FRA Hub"},
]


def test_find_site_unique_match(monkeypatch):
    fake = FakeClient(get={"sites": lambda *_: SITES})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_site("amsterdam"))

    assert payload["returned_count"] == 1
    assert payload["sites"][0]["id"] == "site-1"
    assert payload["match_count"] == 1
    assert payload["ambiguous"] is False
    assert payload["capped"] is False


def test_find_site_ambiguous_returns_all_candidates(monkeypatch):
    fake = FakeClient(get={"sites": lambda *_: SITES})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_site("hub"))

    assert payload["returned_count"] == 3
    assert payload["match_count"] == 3
    assert payload["ambiguous"] is True
    assert {site["id"] for site in payload["sites"]} == {"site-1", "site-2", "site-3"}


def test_find_site_no_match(monkeypatch):
    fake = FakeClient(get={"sites": lambda *_: SITES})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_site("tokyo"))

    assert payload["returned_count"] == 0
    assert payload["match_count"] == 0
    assert "No site match name 'tokyo'" in payload["summary"]
    assert payload["sites"] == []


def test_find_site_matches_display_name(monkeypatch):
    fake = FakeClient(get={"sites": lambda *_: SITES})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_site("lon hub"))

    assert payload["returned_count"] == 1
    assert payload["sites"][0]["id"] == "site-2"


def test_find_site_requires_name(monkeypatch):
    fake = FakeClient(get={"sites": lambda *_: SITES})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_site("  "))

    assert payload["code"] == "invalid_argument"
    assert fake.calls == []


def test_find_element_matches_substring(monkeypatch):
    elements = [
        {"id": "el-1", "name": "IMEMION1", "site_id": "site-1"},
        {"id": "el-2", "name": "IMEMION2", "site_id": "site-1"},
    ]
    fake = FakeClient(get={"elements": lambda *_: elements})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_element("mion1"))

    assert payload["returned_count"] == 1
    assert payload["elements"][0]["id"] == "el-1"
    assert payload["elements"][0]["site_id"] == "site-1"


def test_find_app_caps_candidates_at_fifty(monkeypatch):
    many = [{"id": f"app-{i}", "display_name": f"App {i}", "category": "custom"} for i in range(80)]
    fake = FakeClient(get={"appdefs": lambda *_: many})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_app("app"))

    assert payload["returned_count"] == FIND_CAP
    assert payload["match_count"] == 80
    assert payload["capped"] is True
    assert payload["refine_hint"]
    assert "refine your search" in payload["summary"]


def test_find_app_uncapped_when_under_fifty(monkeypatch):
    few = [{"id": f"app-{i}", "display_name": f"Tool {i}", "category": "custom"} for i in range(3)]
    fake = FakeClient(get={"appdefs": lambda *_: few})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_app("tool"))

    assert payload["returned_count"] == 3
    assert payload["capped"] is False
    assert "refine_hint" not in payload


def test_find_policy_set_searches_all_families(monkeypatch):
    fake = FakeClient(
        get={
            "networkpolicysets": lambda *_: [{"id": "np-1", "name": "Enterprise" }],
            "prioritypolicysets": lambda *_: [{"id": "pp-1", "name": "Guest" }],
            "ngfwsecuritypolicysets": lambda *_: [{"id": "ng-1", "name": "Enterprise" }],
            "natpolicysets": lambda *_: [{"id": "nat-1", "name": "Enterprise" }],
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_policy_set("enterprise"))

    assert payload["returned_count"] == 3
    families = {item["policy_family"] for item in payload["policy_sets"]}
    assert families == {"network", "ngfw", "nat"}
    assert payload["match_count"] == 3
    assert payload["ambiguous"] is True


def test_find_policy_set_skips_failing_families(monkeypatch):
    fake = FakeClient(
        get={
            "networkpolicysets": lambda *_: [{"id": "np-1", "name": "Enterprise" }],
            "prioritypolicysets": lambda *_: {"error": "boom", "status_code": 500},
            "ngfwsecuritypolicysets": lambda *_: [{"id": "ng-1", "name": "Enterprise" }],
            "natpolicysets": lambda *_: [{"id": "nat-1", "name": "Guest" }],
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_policy_set("enterprise"))

    assert payload["returned_count"] == 2
    assert "priority" in payload["family_errors"]


def test_find_policy_set_survives_missing_endpoint(monkeypatch):
    fake = FakeClient(
        get={
            "networkpolicysets": lambda *_: [{"id": "np-1", "name": "Enterprise" }],
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_policy_set("enterprise"))

    assert payload["returned_count"] == 1
    assert payload["family_errors"]["priority"]
    assert payload["family_errors"]["ngfw"]
    assert payload["family_errors"]["nat"]


def test_find_security_zone_matches(monkeypatch):
    zones = [{"id": "z-1", "name": "LAN-Trusted"}, {"id": "z-2", "name": "WAN-Untrusted"}]
    fake = FakeClient(get={"securityzones": lambda *_: zones})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_security_zone("lan"))

    assert payload["returned_count"] == 1
    assert payload["security_zones"][0]["id"] == "z-1"


def test_find_wan_network_matches(monkeypatch):
    networks = [{"id": "w-1", "name": "MPLS-VPN"}, {"id": "w-2", "name": "Internet-BKP"}]
    fake = FakeClient(get={"wannetworks": lambda *_: networks})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_wan_network("mpls"))

    assert payload["returned_count"] == 1
    assert payload["wan_networks"][0]["id"] == "w-1"


def test_find_path_group_matches(monkeypatch):
    groups = [{"id": "pg-1", "name": "Direct-Internet"}, {"id": "pg-2", "name": "Backbone"}]
    fake = FakeClient(get={"pathgroups": lambda *_: groups})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_path_group("direct"))

    assert payload["returned_count"] == 1
    assert payload["path_groups"][0]["id"] == "pg-1"


def test_find_service_label_matches(monkeypatch):
    labels = [{"id": "sl-1", "name": "Gold"}, {"id": "sl-2", "name": "Silver"}]
    fake = FakeClient(get={"servicelabels": lambda *_: labels})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_service_label("gold"))

    assert payload["returned_count"] == 1
    assert payload["service_labels"][0]["id"] == "sl-1"


def test_find_machine_matches(monkeypatch):
    machines = [{"id": "m-1", "name": "ion-5200-01"}, {"id": "m-2", "name": "ion-3200-02"}]
    fake = FakeClient(get={"machines": lambda *_: machines})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(find_machine("5200"))

    assert payload["returned_count"] == 1
    assert payload["machines"][0]["id"] == "m-1"


def test_resolve_path_wan_interface(monkeypatch):
    fake = FakeClient(
        get={"waninterfaces": lambda *_: [{"id": "if-9", "name": "wan-0/0", "element_id": "el-1"}]},
        post={"topology": lambda *_: {"links": []}},
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(resolve_path("site-1", "if-9"))

    assert payload["paths"][0]["resolved"] is True
    assert payload["paths"][0]["kind"] == "wan_interface"
    assert payload["paths"][0]["transport"] == "internet"
    assert payload["resolved_count"] == 1


def test_resolve_path_anynet_link_private_wan(monkeypatch):
    links = [
        {
            "id": "link-1",
            "path_id": "1730000000000000000",
            "source_site_id": "site-1",
            "target_site_id": "site-2",
            "remote_site_id": "site-2",
            "status": "up",
            "vpnlinks": [],
        }
    ]
    fake = FakeClient(
        get={"waninterfaces": lambda *_: []},
        post={"topology": lambda *_: {"links": links}},
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(resolve_path("site-1", "1730000000000000000"))

    assert payload["paths"][0]["resolved"] is True
    assert payload["paths"][0]["kind"] == "anynet_link"
    assert payload["paths"][0]["transport"] == "private_wan"


def test_resolve_path_vpnlink_leg(monkeypatch):
    links = [
        {
            "id": "link-1",
            "path_id": "link-1",
            "source_site_id": "site-1",
            "target_site_id": "site-2",
            "vpnlinks": [
                {"vpnlink_id": "vpn-42", "ep1_site_id": "site-1", "ep2_site_id": "site-2"}
            ],
        }
    ]
    fake = FakeClient(
        get={"waninterfaces": lambda *_: []},
        post={"topology": lambda *_: {"links": links}},
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(resolve_path("site-1", "vpn-42"))

    assert payload["paths"][0]["resolved"] is True
    assert payload["paths"][0]["kind"] == "vpnlink_leg"
    assert payload["paths"][0]["ep1"]["site_id"] == "site-1"
    assert payload["paths"][0]["ep2"]["site_id"] == "site-2"


def test_resolve_path_string_leg_id(monkeypatch):
    links = [
        {
            "id": "link-1",
            "path_id": "link-1",
            "source_site_id": "site-1",
            "target_site_id": "site-2",
            "vpnlinks": ["1737470321551018096", "1737470317025020596"],
        }
    ]
    fake = FakeClient(
        get={"waninterfaces": lambda *_: []},
        post={"topology": lambda *_: {"links": links}},
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(resolve_path("site-1", "1737470321551018096"))

    assert payload["paths"][0]["resolved"] is True
    assert payload["paths"][0]["kind"] == "vpnlink_leg"
    assert payload["paths"][0]["parent_path_id"] == "link-1"


def test_resolve_path_unresolved_is_explicit(monkeypatch):
    fake = FakeClient(
        get={"waninterfaces": lambda *_: []},
        post={"topology": lambda *_: {"links": []}},
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(resolve_path("site-1", "nope-1"))

    assert payload["resolved_count"] == 0
    assert payload["paths"][0]["resolved"] is False
    assert payload["paths"][0]["reason"]


def test_resolve_path_requires_both_ids(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(resolve_path(" ", "path-1"))

    assert payload["code"] == "invalid_argument"
    assert fake.calls == []
