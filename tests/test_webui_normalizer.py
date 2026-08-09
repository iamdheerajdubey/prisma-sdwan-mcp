"""Pin normalizer.py's status/severity mapping against representative payloads.

normalizer.py is ported unchanged from webtester -- it encodes which
controller fields mean "this is down" across payloads that disagree with
each other. This test exists so a future edit to it is caught, not to
re-derive the mapping.
"""
from __future__ import annotations

from webui.app import normalizer as norm


def test_normalize_status_maps_common_controller_values():
    assert norm.normalize_status("down") == "critical"
    assert norm.normalize_status("unreachable") == "critical"
    assert norm.normalize_status("degraded") == "degraded"
    assert norm.normalize_status("up") == "healthy"
    assert norm.normalize_status("connected") == "healthy"
    assert norm.normalize_status("cleared") == "resolved"
    assert norm.normalize_status(None) == "unknown"
    assert norm.normalize_status("something-else") == "unknown"


def test_normalize_severity_maps_numeric_and_text_values():
    assert norm.normalize_severity(4) == "critical"
    assert norm.normalize_severity(3) == "high"
    assert norm.normalize_severity(2) == "medium"
    assert norm.normalize_severity(1) == "low"
    assert norm.normalize_severity("critical") == "critical"
    assert norm.normalize_severity("major") == "high"
    assert norm.normalize_severity("warning") == "medium"
    assert norm.normalize_severity("") == "low"


def test_normalize_sites_from_get_inventory_shape():
    payload = [
        {"id": "site-1", "name": "Amsterdam Branch", "admin_state": "usable", "connectivity_status": "up", "city": "Amsterdam"},
        {"id": "site-2", "name": "Bangalore Office", "connectivity_status": "unreachable"},
    ]
    sites = norm.normalize_sites(payload)
    names = {s["name"]: s["status"] for s in sites}
    assert names["Amsterdam Branch"] == "healthy"
    assert names["Bangalore Office"] == "critical"


def test_normalize_findings_from_get_monitoring_alarms_shape():
    payload = [
        {
            "id": "alarm-1",
            "title": "Primary internet circuit unavailable",
            "severity": "critical",
            "status": "active",
            "site_name": "Bangalore Office",
            "resource_name": "ISP-1",
            "start_time": "2026-08-09T10:00:00Z",
        },
        {
            "id": "alarm-2",
            "title": "BGP peer instability",
            "severity": "minor",
            "status": "cleared",
        },
    ]
    findings = norm.normalize_findings(payload)
    assert findings[0]["severity"] == "critical"
    assert findings[0]["site_name"] == "Bangalore Office"
    assert findings[1]["status"] == "resolved"


def test_normalize_resources_infers_type_from_record_shape():
    payload = [
        {"id": "wan-1", "name": "ISP-1", "wan_id": "wan-1", "site_id": "site-1", "status": "up"},
        {"id": "elem-1", "name": "AMS-ION-01", "element_id": "elem-1", "site_id": "site-1"},
    ]
    resources = norm.normalize_resources(payload)
    types = {r["id"]: r["type"] for r in resources}
    assert types["wan-1"] == "WAN circuit"
    assert types["elem-1"] == "Device"


def test_flatten_records_passes_a_plain_list_through_unchanged():
    payload = [{"id": "1"}, {"id": "2"}]
    assert norm.flatten_records(payload) == payload
