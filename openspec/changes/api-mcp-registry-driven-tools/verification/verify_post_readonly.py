"""Verify the 106 curated POST actions cause no server-side state change.

Method: differential snapshot of the tenant's readable config surface.
  snap A -> snap B          (control window: natural drift while doing nothing but GETs)
  snap B -> run 106 POSTs -> snap C   (treatment window)
Any object whose _etag or _updated_on_utc moves in the treatment window but not
in the control window is a candidate write.

Audit log would be the ideal detector but this service account gets 403 on both
GET /auditlog and POST /auditlog/query, so _etag drift is the detector instead.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "api-mcp")
from prisma_sdwan_mcp.client import PrismaSDWANClient  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("post_readonly_report.json")

TEST_SITE_ID = "1730487989790018996"      # SITE-TESTING-SPARE (admin_state=disabled)
TEST_ELEMENT_ID = "1730487439698012496"   # SPARE-1-TESTING (connected=False, ION powered down)

client = PrismaSDWANClient()
client.login()
sdk = client.sdk

get_reg = json.loads(Path("mcp_GET_domain_registry.json").read_text())
post_reg = json.loads(Path("mcp_POST_domain_registry.json").read_text())

# Snapshot surface: every registry GET action whose SDK method is callable with no
# arguments — i.e. every tenant-wide collection we can read (100 of the 203).
import inspect  # noqa: E402

SNAP_ACTIONS = sorted({
    a["name"]
    for d in get_reg["domains"]
    for a in d["actions"]
    if all(p.default is not inspect.Parameter.empty
           for p in inspect.signature(getattr(sdk.get, a["name"])).parameters.values())
})


def fingerprint(payload):
    """id -> (_etag, _updated_on_utc) for every item; ignores all volatile fields."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if items is None:
        items = [payload]
    if not isinstance(items, list):
        return None
    out = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        key = item.get("id") or f"#{i}"
        out[str(key)] = [item.get("_etag"), item.get("_updated_on_utc")]
    return out


def snapshot(label):
    print(f"--- snapshot {label} ({len(SNAP_ACTIONS)} collections)", flush=True)
    started = time.time()
    snap = {}
    for name in SNAP_ACTIONS:
        try:
            client.login()  # no-op unless the 839s token has expired
            resp = getattr(sdk.get, name)()
            snap[name] = {
                "status": resp.status_code,
                "fp": fingerprint(getattr(resp, "cgx_content", None)),
            }
        except Exception as exc:  # noqa: BLE001 - recording, not handling
            snap[name] = {"status": None, "error": str(exc), "fp": None}
    print(f"    done in {time.time() - started:.0f}s", flush=True)
    return snap


def diff(before, after):
    changes = []
    for name in SNAP_ACTIONS:
        b, a = before.get(name, {}).get("fp"), after.get(name, {}).get("fp")
        if b is None or a is None:
            continue
        for key in set(b) | set(a):
            if b.get(key) != a.get(key):
                changes.append({"collection": name, "id": key,
                                "before": b.get(key), "after": a.get(key)})
    return changes


def body_for(action):
    """Minimal query body. Registry example_values fill anything mandatory-looking."""
    data = {"limit": 1}
    for p in action.get("input_parameters", []):
        name, example = p.get("name"), p.get("example_value")
        if name in ("limit", "total_count", "next_query", "sort_params",
                    "sort_case_insensitive", "getDeleted", "eq"):
            continue
        if example not in (None, {}, []):
            data[name] = example
    return data


FILL = {"site_id": TEST_SITE_ID, "element_id": TEST_ELEMENT_ID}


def path_args(call):
    """Positional path args in the SDK method's own declared order, before `data`."""
    sig = inspect.signature(getattr(sdk.post, call))
    args, unresolved = [], []
    for pname, p in sig.parameters.items():
        if pname == "data":
            break
        if p.default is not inspect.Parameter.empty:
            continue
        if pname in FILL:
            args.append(FILL[pname])
        else:
            unresolved.append(pname)
    return args, unresolved


snap_a = snapshot("A (control start)")
snap_b = snapshot("B (control end / treatment start)")
control_changes = diff(snap_a, snap_b)
print(f"control-window changes: {len(control_changes)}", flush=True)

print(f"--- executing {sum(len(d['actions']) for d in post_reg['domains'])} POST actions", flush=True)
results = []
for dom in post_reg["domains"]:
    for action in dom["actions"]:
        name, call = action["name"], action["sdk_call"]
        pargs, unresolved = path_args(call)
        data = body_for(action)
        entry = {"domain": dom["domain"], "action": name, "sdk_call": call,
                 "url": action.get("url_template"), "body": data, "path_args": pargs}
        if unresolved:
            entry.update(status=None, outcome="skipped_unresolvable_path_param",
                         error_body=f"no test value for {unresolved}")
            results.append(entry)
            continue
        try:
            client.login()  # no-op unless the 839s token has expired
            resp = getattr(sdk.post, call)(*pargs, data)
            content = getattr(resp, "cgx_content", None)
            entry.update(
                status=resp.status_code,
                outcome="ok" if 200 <= resp.status_code < 300 else "http_error",
                returned_items=len(content.get("items", [])) if isinstance(content, dict) else None,
                total_count=content.get("total_count") if isinstance(content, dict) else None,
                error_body=None if 200 <= resp.status_code < 300
                else json.dumps(content)[:300],
            )
        except Exception as exc:  # noqa: BLE001
            entry.update(status=None, outcome="exception", error_body=str(exc)[:300])
        results.append(entry)
        print(f"  {entry['outcome']:<12} {entry.get('status') or '---':>4}  "
              f"{dom['domain']}/{name}", flush=True)

snap_c = snapshot("C (treatment end)")
treatment_changes = diff(snap_b, snap_c)
print(f"treatment-window changes: {len(treatment_changes)}", flush=True)

control_keys = {(c["collection"], c["id"]) for c in control_changes}
suspects = [c for c in treatment_changes if (c["collection"], c["id"]) not in control_keys]

report = {
    "test_target": {"site": "SITE-TESTING-SPARE", "site_id": TEST_SITE_ID,
                    "element": "SPARE-1-TESTING", "element_id": TEST_ELEMENT_ID,
                    "element_connected": False},
    "detector": "_etag/_updated_on_utc drift across all no-path-param GET collections; "
                "auditlog unavailable (403 for this service account)",
    "snapshot_collections": len(SNAP_ACTIONS),
    "control_window_changes": control_changes,
    "treatment_window_changes": treatment_changes,
    "suspect_writes": suspects,
    "post_results": results,
    "summary": {
        "total_actions": len(results),
        "ok": sum(1 for r in results if r["outcome"] == "ok"),
        "http_error": sum(1 for r in results if r["outcome"] == "http_error"),
        "exception": sum(1 for r in results if r["outcome"] == "exception"),
        "skipped": sum(1 for r in results if r["outcome"] == "skipped_unresolvable_path_param"),
        "suspect_writes": len(suspects),
    },
}
OUT.write_text(json.dumps(report, indent=1))
print("\n=== SUMMARY ===")
print(json.dumps(report["summary"], indent=1))
print("suspects:", json.dumps(suspects, indent=1)[:2000])
print("report ->", OUT)
