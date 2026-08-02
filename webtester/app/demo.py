from __future__ import annotations

from datetime import datetime, timedelta, timezone


NOW = datetime.now(timezone.utc)

SITES = [
    {"id": "site-amsterdam", "name": "Amsterdam Branch", "status": "degraded", "city": "Amsterdam", "country": "Netherlands", "device_count": 2, "active_findings": 1},
    {"id": "site-bangalore", "name": "Bangalore Office", "status": "critical", "city": "Bengaluru", "country": "India", "device_count": 3, "active_findings": 1},
    {"id": "site-london", "name": "London Office", "status": "healthy", "city": "London", "country": "United Kingdom", "device_count": 2, "active_findings": 0},
    {"id": "site-singapore", "name": "Singapore Hub", "status": "healthy", "city": "Singapore", "country": "Singapore", "device_count": 4, "active_findings": 0},
    {"id": "site-mumbai", "name": "Mumbai Branch", "status": "degraded", "city": "Mumbai", "country": "India", "device_count": 2, "active_findings": 1},
    {"id": "site-new-york", "name": "New York Office", "status": "healthy", "city": "New York", "country": "United States", "device_count": 3, "active_findings": 0},
]

FINDINGS = [
    {
        "id": "finding-bangalore-circuit",
        "title": "Primary internet circuit unavailable",
        "severity": "critical",
        "status": "active",
        "site_name": "Bangalore Office",
        "resource": "ISP-1",
        "started": (NOW - timedelta(minutes=22)).isoformat(),
        "impact": "Connectivity remains available through the backup circuit, but resilience is reduced.",
        "recommendation": "Check the provider circuit and confirm the branch remains stable on ISP-2.",
    },
    {
        "id": "finding-amsterdam-loss",
        "title": "Packet loss above normal",
        "severity": "high",
        "status": "active",
        "site_name": "Amsterdam Branch",
        "resource": "ISP-1",
        "started": (NOW - timedelta(minutes=48)).isoformat(),
        "impact": "Voice, video, and interactive SaaS applications may experience degraded quality.",
        "recommendation": "Compare ISP-1 performance with the healthy backup path and review provider health.",
    },
    {
        "id": "finding-mumbai-bgp",
        "title": "BGP peer instability detected",
        "severity": "medium",
        "status": "active",
        "site_name": "Mumbai Branch",
        "resource": "Peer 10.20.30.1",
        "started": (NOW - timedelta(hours=2)).isoformat(),
        "impact": "Route reachability may be intermittently reduced.",
        "recommendation": "Verify peer reachability, session transitions, and recent routing changes.",
    },
]

RESOURCES = [
    {"id": "device-amsterdam-01", "name": "AMS-ION-01", "type": "Device", "status": "healthy", "site_id": "site-amsterdam", "site_name": "Amsterdam Branch", "model": "ION 3200", "description": "Primary branch appliance"},
    {"id": "device-bangalore-01", "name": "BLR-ION-01", "type": "Device", "status": "healthy", "site_id": "site-bangalore", "site_name": "Bangalore Office", "model": "ION 5200", "description": "Primary branch appliance"},
    {"id": "wan-amsterdam-isp1", "name": "ISP-1", "type": "WAN circuit", "status": "degraded", "site_id": "site-amsterdam", "site_name": "Amsterdam Branch", "model": "Internet", "description": "Primary internet circuit"},
    {"id": "wan-amsterdam-isp2", "name": "ISP-2", "type": "WAN circuit", "status": "healthy", "site_id": "site-amsterdam", "site_name": "Amsterdam Branch", "model": "Internet", "description": "Backup internet circuit"},
    {"id": "wan-bangalore-isp1", "name": "ISP-1", "type": "WAN circuit", "status": "critical", "site_id": "site-bangalore", "site_name": "Bangalore Office", "model": "Internet", "description": "Primary internet circuit"},
    {"id": "wan-bangalore-isp2", "name": "ISP-2", "type": "WAN circuit", "status": "healthy", "site_id": "site-bangalore", "site_name": "Bangalore Office", "model": "Internet", "description": "Backup internet circuit"},
]


def dashboard():
    return {
        "summary": {
            "sites_total": len(SITES),
            "sites_healthy": sum(site["status"] == "healthy" for site in SITES),
            "sites_degraded": sum(site["status"] == "degraded" for site in SITES),
            "sites_critical": sum(site["status"] == "critical" for site in SITES),
            "sites_unknown": 0,
            "active_findings": len(FINDINGS),
            "critical_findings": 1,
            "high_findings": 1,
            "updated_at": NOW.isoformat(),
        },
        "attention": FINDINGS,
        "sites": sorted(SITES, key=lambda site: {"critical": 0, "degraded": 1, "healthy": 2}[site["status"]]),
        "data_quality": {"complete": True, "missing": [], "message": "Preview data loaded."},
    }


def site_detail(site_id: str):
    site = next((item for item in SITES if item["id"] == site_id), SITES[0])
    resources = [item for item in RESOURCES if item.get("site_id") == site["id"]]
    devices = [item for item in resources if item["type"] == "Device"]
    connectivity = [item for item in resources if item["type"] != "Device"]
    findings = [item for item in FINDINGS if item["site_name"] == site["name"]]
    return {
        "site": site,
        "summary": {
            "devices_total": len(devices),
            "devices_healthy": sum(item["status"] == "healthy" for item in devices),
            "connectivity_total": len(connectivity),
            "connectivity_degraded": sum(item["status"] in ("critical", "degraded") for item in connectivity),
            "active_findings": len(findings),
        },
        "devices": devices,
        "connectivity": connectivity,
        "findings": findings,
        "sources": [{"tool": "preview-data", "ok": True, "error": None, "score": 100}],
    }


def telemetry(site_id: str = ""):
    points = []
    for index in range(36):
        timestamp = (NOW - timedelta(minutes=(35 - index) * 5)).isoformat()
        degraded = site_id in ("", "site-amsterdam") and index > 20
        points.append({
            "timestamp": timestamp,
            "latency_ms": round(31 + (index % 5) * 1.4 + (78 if degraded else 0), 1),
            "packet_loss_pct": round(0.2 + (index % 3) * 0.1 + (12.5 if degraded else 0), 1),
            "jitter_ms": round(3.2 + (index % 4) * 0.5 + (11 if degraded else 0), 1),
            "utilization_pct": round(42 + (index % 7) * 3.1, 1),
            "availability_pct": 99.9 if not degraded else 97.4,
        })
    summary = {}
    for metric in ("latency_ms", "packet_loss_pct", "jitter_ms", "utilization_pct", "availability_pct"):
        values = [point[metric] for point in points]
        summary[metric] = {"current": values[-1], "average": round(sum(values) / len(values), 2), "maximum": max(values)}
    return {"summary": summary, "points": points, "sources": [{"tool": "preview-data", "ok": True}], "raw_source_count": 1}
