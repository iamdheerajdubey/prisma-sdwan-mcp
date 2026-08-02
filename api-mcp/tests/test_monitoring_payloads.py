import json
from types import SimpleNamespace

from prisma_sdwan_mcp import registry
from prisma_sdwan_mcp.tools.monitoring import get_alarms, get_events, get_flows, get_link_metrics, get_probe_metrics


class FakeClient:
    class SDK:
        class Post:
            pass

        post = Post()

    def __init__(self):
        self.sdk = self.SDK()
        self.body = None

        def monitor_flows(data):
            self.body = data
            return []

        self.sdk.post.monitor_flows = monitor_flows

    def call_sdk_post(self, function, data, **kwargs):
        return function(data)


def test_flows_use_the_accepted_site_filter_shape(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(get_flows("site-1", hours=1, limit=20))

    assert payload["returned_count"] == 0
    assert fake.body["filter"] == {"site": ["site-1"]}
    assert fake.body["debug_level"] == "all"
    assert fake.body["page_size"] == 1000
    assert fake.body["dest_page"] == 1
    assert "end_time" in fake.body


def test_flows_server_side_filters_go_into_the_payload(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(registry, "client", fake)

    json.loads(
        get_flows(
            "site-1",
            app="app-9",
            element_id="el-3",
            path_id="1730000000000000000",
            waninterface_id="if-7",
        )
    )

    assert fake.body["filter"] == {
        "site": ["site-1"],
        "app": ["app-9"],
        "element": ["el-3"],
        "path": ["1730000000000000000"],
        "wan_interface": ["if-7"],
    }


def test_flows_digest_breakdowns_and_top_talkers(monkeypatch):
    records = [
        {"app_id": "zoom", "path_id": "p-1", "flow_action": "allow", "src_ip": "10.0.0.1", "dst_ip": "10.9.9.9", "bytes_c2s": 100, "bytes_s2c": 200},
        {"app_id": "zoom", "path_id": "p-1", "flow_action": "allow", "src_ip": "10.0.0.1", "dst_ip": "10.9.9.9", "bytes_c2s": 100, "bytes_s2c": 200},
        {"app_id": "s3", "path_id": "p-2", "flow_action": "BlockedByPolicy", "src_ip": "10.0.0.2", "dst_ip": "10.8.8.8", "bytes_c2s": 50, "bytes_s2c": 0},
    ]

    def monitor_flows(data):
        fake.body = data
        return {"flows": {"items": records}}

    fake = FakeClient()
    fake.sdk.post.monitor_flows = monitor_flows
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(get_flows("site-1"))

    assert payload["digest_mode"] is True
    assert payload["returned_count"] == 0
    digest = payload["digest"]
    assert digest["total"] == 3
    assert digest["by_app"] == {"zoom": 2, "s3": 1}
    assert digest["by_path"] == {"p-1": 2, "p-2": 1}
    assert digest["by_action"] == {"allow": 2, "BlockedByPolicy": 1}
    assert digest["top_talkers"][0]["src_ip"] == "10.0.0.1"
    assert digest["top_talkers"][0]["total_bytes"] == 600


def test_flows_raw_mode_returns_records_with_page(monkeypatch):
    records = [{"flow_id": f"f-{i}", "app_id": "zoom"} for i in range(3)]

    def monitor_flows(data):
        fake.body = data
        return {"flows": {"items": records}}

    fake = FakeClient()
    fake.sdk.post.monitor_flows = monitor_flows
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(get_flows("site-1", raw=True, page=2, limit=10))

    assert payload["raw"] is True
    assert payload["page"] == 2
    assert payload["returned_count"] == 3
    assert fake.body["page_size"] == 10
    assert fake.body["dest_page"] == 2
    assert "digest_mode" not in payload


def test_flows_limit_capped_at_200_and_page_validated(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(registry, "client", fake)

    too_big = json.loads(get_flows("site-1", raw=True, limit=201))
    assert too_big["code"] == "invalid_limit"

    bad_page = json.loads(get_flows("site-1", raw=True, page=0))
    assert bad_page["code"] == "invalid_argument"


def test_flows_rejects_empty_filter_values(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(get_flows("site-1", app=" "))

    assert payload["code"] == "invalid_argument"
    assert fake.body is None


class TelemetryClient:
    def __init__(self):
        self.get = SimpleNamespace(waninterfaces=lambda *_: [])
        self.post = SimpleNamespace(
            monitor_metrics=lambda data: self._capture("metrics", data),
            monitor_lqm_point_metrics=lambda data: self._capture("lqm", data),
            monitor_probe_point_metrics=lambda data: self._capture("probe", data),
        )
        self.sdk = SimpleNamespace(get=self.get, post=self.post)
        self.bodies = {}

    def _capture(self, name, data):
        self.bodies[name] = data
        return {"metrics": []}

    def call_sdk(self, function, *args, **kwargs):
        return function(*args, **kwargs)

    def call_sdk_post(self, function, data, **kwargs):
        return function(data)


def test_verified_metric_names_and_lqm_payload_shape(monkeypatch):
    fake = TelemetryClient()
    monkeypatch.setattr(registry, "client", fake)

    link_payload = json.loads(get_link_metrics("site-1"))
    probe_payload = json.loads(get_probe_metrics("site-1"))

    assert link_payload["returned_count"] == 1
    assert [metric["name"] for metric in fake.bodies["lqm"]["metrics"]] == [
        "LqmLatencyPointMetric",
        "LqmPktLossPointMetric",
        "LqmJitterPointMetric",
        "LqmMosPointMetric",
    ]
    assert fake.bodies["lqm"]["filter"] == {"site": ["site-1"]}
    assert fake.bodies["lqm"]["start_time"]
    assert "end_time" not in fake.bodies["lqm"]
    assert [metric["name"] for metric in fake.bodies["probe"]["metrics"]] == [
        "ProbeLatencyPointMetric",
        "ProbeJitterPointMetric",
        "ProbePktLossPointMetric",
    ]
    assert probe_payload["returned_count"] == 0


class EventsClient:
    def __init__(self):
        self.sdk = SimpleNamespace(
            post=SimpleNamespace(events_query=self._capture),
        )
        self.bodies = []
        self._payload = None

    def _capture(self, data):
        self.bodies.append(data)
        return [] if self._payload is None else self._payload

    def call_sdk(self, function, *args, **kwargs):
        return function(*args, **kwargs)

    def call_sdk_post(self, function, data, **kwargs):
        return function(data)


def test_events_scoping_args_land_in_the_payload(monkeypatch):
    fake = EventsClient()
    monkeypatch.setattr(registry, "client", fake)

    json.loads(
        get_events(
            limit=5,
            site_id="site-1",
            element_id="el-1",
            severity="critical, major",
            start_time="2026-07-30T00:00:00.000Z",
            end_time="2026-07-30T23:59:59.000Z",
            last=10,
        )
    )

    body = fake.bodies[0]
    assert body["query"] == {"site": ["site-1"], "element": ["el-1"]}
    assert body["severity"] == ["critical", "major"]
    assert body["start_time"] == "2026-07-30T00:00:00.000Z"
    assert body["end_time"] == "2026-07-30T23:59:59.000Z"
    assert body["limit"]["count"] == 10


def test_events_no_argument_payload_unchanged(monkeypatch):
    fake = EventsClient()
    monkeypatch.setattr(registry, "client", fake)

    json.loads(get_events(limit=20))

    body = fake.bodies[0]
    assert body == {
        "severity": ["critical", "major", "minor"],
        "limit": {"count": 20, "sort_on": "time", "sort_order": "descending"},
    }

    fake2 = EventsClient()
    monkeypatch.setattr(registry, "client", fake2)

    json.loads(get_alarms(limit=20))

    assert fake2.bodies[0]["severity"] == ["major", "critical"]


def test_events_rejects_bad_scoping_values(monkeypatch):
    fake = EventsClient()
    monkeypatch.setattr(registry, "client", fake)

    bad_site = json.loads(get_events(site_id=" "))
    assert bad_site["code"] == "invalid_argument"

    bad_last = json.loads(get_events(last=0))
    assert bad_last["code"] == "invalid_argument"

    bad_severity = json.loads(get_alarms(severity=","))
    assert bad_severity["code"] == "invalid_argument"


def test_link_metrics_element_scopes_utilization_only(monkeypatch):
    fake = TelemetryClient()
    monkeypatch.setattr(registry, "client", fake)

    json.loads(get_link_metrics("site-1", element_id="el-9"))

    assert fake.bodies["metrics"]["filter"] == {"site": ["site-1"], "element": ["el-9"]}
    assert fake.bodies["lqm"]["filter"] == {"site": ["site-1"]}


def test_link_metrics_raw_returns_datapoint_series(monkeypatch):
    class RawTelemetry(TelemetryClient):
        def __init__(self):
            super().__init__()
            self._lqm_returned = False

        def _capture(self, name, data):
            self.bodies[name] = data
            if name == "lqm":
                self._lqm_returned = True
                return {
                    "metrics": [
                        {
                            "name": "LqmLatencyPointMetric",
                            "series": [
                                {
                                    "path_id": "1730000000000000000",
                                    "data": [{"datapoints": [{"ts": "t1", "rtt_latency": 12}]}],
                                }
                            ],
                        }
                    ]
                }
            return {"metrics": []}

    fake = RawTelemetry()
    monkeypatch.setattr(registry, "client", fake)

    payload = json.loads(get_link_metrics("site-1", raw=True))

    assert payload["raw_datapoints"] is True
    assert fake._lqm_returned
    assert payload["link_quality"][0]["datapoints"] == [{"ts": "t1", "rtt_latency": 12}]