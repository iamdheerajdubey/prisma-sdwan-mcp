import json
from types import SimpleNamespace

from prisma_sdwan_mcp import registry
from prisma_sdwan_mcp.tools import inventory, monitoring, network, policy, routing


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


def test_interface_status_fans_out_and_keeps_per_interface_error(monkeypatch):
    def interfaces(*_):
        return [{"id": "if-1"}, {"id": "if-2"}]

    def status(_site, _element, interface_id):
        if interface_id == "if-2":
            return {"error": "interface unavailable", "status_code": 503}
        return {"id": interface_id, "status": "up", "admin_up": True}

    fake = FakeClient(get={"interfaces": interfaces, "interfaces_status": status})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(monitoring.get_interface_status("site-1", "element-1"))

    assert payload["returned_count"] == 2
    assert payload["interfaces"][0]["status"] == "up"
    assert payload["interfaces"][1]["interface_id"] == "if-2"
    assert payload["interfaces"][1]["error"] == "interface unavailable"


def test_bgp_status_counts_session_states(monkeypatch):
    fake = FakeClient(
        get={
            "bgppeers_status": lambda *_: [
                {"id": "peer-1", "state": "Established"},
                {"id": "peer-2", "state": "Idle"},
            ]
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(routing.get_bgp_status("site-1", "element-1"))

    assert payload["established_count"] == 1
    assert payload["not_established_count"] == 1


def test_bgp_prefixes_validates_peer_and_passes_api_version(monkeypatch):
    calls = []

    def prefixes(*args, **kwargs):
        calls.append((args, kwargs))
        return [{"prefix": "10.0.0.0/24"}]

    fake = FakeClient(get={"bgppeers_reachableprefixes": prefixes})
    monkeypatch.setattr(registry, "client", fake)

    missing = json.loads(routing.get_bgp_prefixes("site-1", "element-1", " "))
    assert missing["code"] == "invalid_argument"
    assert "bgppeer_id" in missing["message"]
    assert calls == []

    payload = json.loads(routing.get_bgp_prefixes("site-1", "element-1", "peer-1"))
    assert payload["returned_count"] == 1
    assert calls[0][1]["api_version"] == "v2.1"


def test_bgp_status_flags_established_peer_with_zero_prefixes(monkeypatch):
    peers = [
        {"id": "peer-1", "state": "Established"},
        {"id": "peer-2", "state": "Established"},
        {"id": "peer-3", "state": "Idle"},
    ]
    prefix_results = {
        "peer-1": [{"prefix": "10.0.0.0/24"}, {"prefix": "10.1.0.0/24", "filtered": True}],
        "peer-2": [],
        "peer-3": [{"prefix": "192.168.0.0/24"}],
    }
    fake = FakeClient(
        get={
            "bgppeers_status": lambda *_: peers,
            "bgppeers_reachableprefixes": lambda _site, _element, peer_id, **_kw: prefix_results[peer_id],
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(routing.get_bgp_status("site-1", "element-1", include_prefixes=True))

    by_id = {peer["id"]: peer for peer in payload["peers"]}
    assert by_id["peer-1"]["reachable_prefix_count"] == 2
    assert by_id["peer-1"]["filtered_prefix_count"] == 1
    assert by_id["peer-1"]["established_zero_prefixes"] is False
    assert by_id["peer-2"]["established_zero_prefixes"] is True
    assert by_id["peer-3"]["established_zero_prefixes"] is False
    assert payload["zero_prefix_peers"] == 1
    assert payload["prefix_indicator_unobserved"] is False


def test_bgp_status_without_include_prefixes_is_unchanged(monkeypatch):
    fake = FakeClient(
        get={"bgppeers_status": lambda *_: [{"id": "peer-1", "state": "Established"}]}
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(routing.get_bgp_status("site-1", "element-1"))

    assert payload["established_count"] == 1
    assert "zero_prefix_peers" not in payload
    assert "reachable_prefix_count" not in payload["peers"][0]


def test_bgp_status_prefix_indicator_unobserved(monkeypatch):
    fake = FakeClient(
        get={
            "bgppeers_status": lambda *_: [{"id": "peer-1", "state": "Established"}],
            "bgppeers_reachableprefixes": lambda *_a, **_kw: [{"prefix": "10.0.0.0/24"}],
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(routing.get_bgp_status("site-1", "element-1", include_prefixes=True))

    assert payload["peers"][0]["reachable_prefix_count"] == 1
    assert payload["prefix_indicator_unobserved"] is True


def test_bgp_prefixes_selects_endpoint_and_marks_discovered_unconfirmed(monkeypatch):
    calls = []

    def prefixes(*args, **kwargs):
        calls.append((args, kwargs))
        return [{"prefix": "10.0.0.0/24", "next_hop": "192.0.2.1"}]

    fake = FakeClient(
        get={
            "bgppeers_reachableprefixes": prefixes,
            "bgppeers_advertisedprefixes": prefixes,
            "bgppeers_discoveredprefixes": prefixes,
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    reachable = json.loads(routing.get_bgp_prefixes("s", "e", "p", prefix_type="reachable"))
    assert reachable["prefix_type"] == "reachable"
    assert "schema_unconfirmed" not in reachable

    advertised = json.loads(routing.get_bgp_prefixes("s", "e", "p", prefix_type="advertised"))
    assert advertised["prefix_type"] == "advertised"
    assert calls[-1][1]["api_version"] == "v2.1"

    discovered = json.loads(routing.get_bgp_prefixes("s", "e", "p", prefix_type="discovered"))
    assert discovered["prefix_type"] == "discovered"
    assert discovered["schema_unconfirmed"] is True
    assert calls[-1][1]["api_version"] == "v2.2"


def test_bgp_prefixes_rejects_unknown_prefix_type(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(routing.get_bgp_prefixes("s", "e", "p", prefix_type="bogus"))

    assert payload["code"] == "invalid_argument"
    assert fake.calls == []


def test_site_paths_reports_up_and_down_counts(monkeypatch):
    topology = {
        "nodes": [{"id": "site-1"}],
        "links": [
            {"id": "path-1", "source_site_id": "site-1", "target_site_id": "site-2", "status": "up"},
            {"id": "path-2", "source_site_id": "site-3", "target_site_id": "site-1", "status": "down"},
        ],
    }
    fake = FakeClient(post={"topology": lambda *_: topology})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(network.get_site_paths("site-1"))

    assert payload["returned_count"] == 2
    assert payload["up_count"] == 1
    assert payload["down_count"] == 1


def test_unfiltered_app_defs_returns_histogram_only(monkeypatch):
    fake = FakeClient(
        get={
            "appdefs": lambda *_: [
                {"id": "1", "display_name": "Office", "category": "business", "app_type": "custom"},
                {"id": "2", "display_name": "Zoom", "category": "real-time", "app_type": "custom"},
            ]
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(inventory.get_app_defs())

    assert payload["returned_count"] == 0
    assert "app_defs" not in payload
    assert payload["categories"] == {"business": 1, "real-time": 1}


def test_policy_families_are_returned_independently(monkeypatch):
    fake = FakeClient(
        get={
            "networkpolicysets": lambda *_: [{"id": "network-1"}],
            "prioritypolicysets": lambda *_: [],
            "ngfwsecuritypolicysets": lambda *_: {"error": "denied", "status_code": 403},
            "natpolicysets": lambda *_: [{"id": "nat-1"}],
        }
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(policy.get_policy_sets())

    assert payload["family_counts"] == {"network": 1, "priority": 0, "ngfw": 0, "nat": 1}
    assert payload["family_errors"]["ngfw"] == "denied"
    assert {item["policy_family"] for item in payload["policy_sets"]} == {"network", "nat"}


def test_vpnlink_status_passes_through_upstream_fields(monkeypatch):
    calls = []

    def status(vpnlink_id, **kwargs):
        calls.append((vpnlink_id, kwargs))
        return {
            "active": True,
            "usable": True,
            "link_up": False,
            "common_cipher": "AES-256-GCM",
            "ep1_keep_alive_interval": 10,
            "ep1_keep_alive_failure_count": 3,
            "ep2_keep_alive_interval": 10,
            "ep2_keep_alive_failure_count": 0,
            "ep1_site_id": "site-1",
            "ep1_element_id": "el-1",
            "ep1_interface_id": "if-1",
            "ep2_site_id": "site-2",
            "ep2_element_id": "el-2",
            "ep2_interface_id": "if-2",
            "unexpected_field": "dropped",
        }

    fake = FakeClient(get={"vpnlinks_status": status})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(network.get_vpnlink_status("leg-1"))

    assert calls[0] == ("leg-1", {"api_version": "v2.2"})
    assert payload["vpnlink_status"][0]["active"] is True
    assert payload["vpnlink_status"][0]["usable"] is True
    assert payload["vpnlink_status"][0]["link_up"] is False
    assert payload["vpnlink_status"][0]["common_cipher"] == "AES-256-GCM"
    assert payload["vpnlink_status"][0]["ep1_keep_alive_interval"] == 10
    assert payload["vpnlink_status"][0]["ep1_keep_alive_failure_count"] == 3
    assert payload["vpnlink_status"][0]["ep1_site_id"] == "site-1"
    assert payload["vpnlink_status"][0]["ep2_interface_id"] == "if-2"
    assert payload["vpnlink_status"][0]["unexpected_field"] == "dropped"


def test_vpnlink_status_unknown_id_returns_structured_error(monkeypatch):
    fake = FakeClient(
        get={"vpnlinks_status": lambda *_, **__: {"error": "Resource not found", "status_code": 404}}
    )
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(network.get_vpnlink_status("nope-1"))

    assert payload["code"] == "not_found"
    assert payload["status_code"] == 404
    assert "nope-1" in payload["message"]


def test_vpnlink_status_requires_id(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(network.get_vpnlink_status(" "))

    assert payload["code"] == "invalid_argument"
    assert fake.calls == []


def test_vpnlink_state_returns_enabled_and_al_id(monkeypatch):
    calls = []

    def state(vpnlink_id, **kwargs):
        calls.append((vpnlink_id, kwargs))
        return {"enabled": False, "al_id": "1730000000000000000"}

    fake = FakeClient(get={"vpnlinks_state": state})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(network.get_vpnlink_state("leg-1"))

    assert calls[0] == ("leg-1", {"api_version": "v2.0"})
    assert payload["vpnlink_state"][0]["enabled"] is False
    assert payload["vpnlink_state"][0]["al_id"] == "1730000000000000000"


def test_basenet_topology_derives_legs_from_anynet(monkeypatch):
    calls = []
    topology = {
        "nodes": [{"id": "site-1"}, {"id": "site-2"}],
        "links": [
            {
                "id": "b-1",
                "path_id": "1730000000000000000",
                "source_site_id": "site-1",
                "target_site_id": "site-2",
                "vpnlinks": ["leg-1", "leg-2"],
            },
            {"id": "b-2", "source_site_id": "site-3", "target_site_id": "site-4", "vpnlinks": ["leg-9"]},
        ],
    }

    def post(*args, **kwargs):
        calls.append(args[0])
        return topology

    def status(vpnlink_id, **_kwargs):
        if vpnlink_id == "leg-1":
            return {
                "active": True,
                "usable": True,
                "link_up": True,
                "ep1_site_id": "site-1",
                "ep1_element_id": "el-1",
                "ep1_interface_id": "if-1",
                "ep2_site_id": "site-2",
                "ep2_element_id": "el-2",
                "ep2_interface_id": "if-2",
            }
        return {"error": "leg gone", "status_code": 404}

    fake = FakeClient(get={"vpnlinks_status": status}, post={"topology": post})
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(network.get_basenet_topology("site-1"))

    assert calls == [{"type": "anynet"}]
    assert payload["derived_from_anynet"] is True
    assert payload["anynet_link_count"] == 1
    assert payload["leg_count"] == 2
    assert payload["returned_count"] == 2
    by_leg = {entry["vpnlink_id"]: entry for entry in payload["links"]}
    assert by_leg["leg-1"]["anynet_link_id"] == "1730000000000000000"
    assert by_leg["leg-1"]["element_id"] == "el-1"
    assert by_leg["leg-1"]["source_elem_if_id"] == "if-1"
    assert by_leg["leg-1"]["target_elem_if_id"] == "if-2"
    assert by_leg["leg-1"]["in_use"] is True
    assert by_leg["leg-2"]["error"] == "leg gone"
    assert payload["site_present"] is True


def test_basenet_topology_unknown_site_vs_no_links(monkeypatch):
    fake = FakeClient(
        get={"vpnlinks_status": lambda *_a, **_kw: {"error": "nope"}},
        post={"topology": lambda *_, **__: {"nodes": [], "links": []}},
    )
    monkeypatch.setattr(registry, "client", fake)

    unknown = json.loads(network.get_basenet_topology("ghost"))
    assert unknown["returned_count"] == 0
    assert unknown["site_present"] is False
    assert "not present in the topology" in unknown["summary"]

    fake = FakeClient(
        get={"vpnlinks_status": lambda *_a, **_kw: {"error": "nope"}},
        post={"topology": lambda *_, **__: {"nodes": [{"id": "site-1"}], "links": []}},
    )
    monkeypatch.setattr(registry, "client", fake)

    none = json.loads(network.get_basenet_topology("site-1"))
    assert none["returned_count"] == 0
    assert none["site_present"] is True
    assert "No basenet legs found" in none["summary"]