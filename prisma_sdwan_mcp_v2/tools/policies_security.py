from __future__ import annotations

from typing import Literal, Optional

from ..mcp import READ_ONLY, mcp
from ..response import collection_json, error_json, single_json
from .common import execute, fail_from_upstream, handle_error, records, resolve, site_element

PolicyFamily = Literal["network", "priority", "nat", "security", "performance", "all"]
PolicyOperation = Literal["sets", "stacks", "rules", "status"]
SecurityOperation = Literal[
    "zones",
    "site_zones",
    "element_zones",
    "applications",
    "application_version",
    "global_prefixes",
    "local_prefixes",
    "sdwan_apps",
    "sdwan_app_status",
    "sdwan_app_configs",
]

POLICY_MAP = {
    "network": {
        "kind": "network_policy",
        "sets": "network_priority_policies.networkpolicysets",
        "stacks": "network_priority_policies.networkpolicysetstacks",
        "rules": "network_priority_policies.networkpolicyrules",
        "status": "network_priority_policies.networkpolicysets_status",
        "id_param": "networkpolicyset_id",
    },
    "priority": {
        "kind": "priority_policy",
        "sets": "network_priority_policies.prioritypolicysets",
        "stacks": "network_priority_policies.prioritypolicysetstacks",
        "rules": "network_priority_policies.prioritypolicyrules",
        "status": "network_priority_policies.prioritypolicysets_status",
        "id_param": "prioritypolicyset_id",
    },
    "nat": {
        "kind": "nat_policy",
        "sets": "nat_policies.natpolicysets",
        "stacks": "nat_policies.natpolicysetstacks",
        "rules": "nat_policies.natpolicyrules",
        "status": "nat_policies.natpolicysets_status",
        "id_param": "natpolicyset_id",
    },
    "security": {
        "kind": "security_policy",
        "sets": "security_policies.ngfwsecuritypolicysets",
        "stacks": "security_policies.ngfwsecuritypolicysetstacks",
        "rules": "security_policies.ngfwsecuritypolicyrules",
        "status": None,
        "id_param": "ngfwsecuritypolicyset_id",
    },
    "performance": {
        "kind": "performance_policy",
        "sets": "performance_management.perfmgmtpolicysets",
        "stacks": "performance_management.perfmgmtpolicysetstacks",
        "rules": "performance_management.perfmgmtpolicysets_perfmgmtpolicyrules",
        "status": "performance_management.perfmgmtpolicysets_status",
        "id_param": "perfmgmtpolicyset_id",
    },
}


@mcp.tool(annotations=READ_ONLY)
def get_policies(
    family: PolicyFamily,
    operation: PolicyOperation = "sets",
    policy: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect the major Prisma SD-WAN policy families using human policy names.

    ``sets`` and ``stacks`` can be listed tenant-wide. ``rules`` and ``status``
    require ``policy`` as an exact/partial name or ID; ambiguous policy names are
    never auto-selected. Security policy-set status is not present in the source
    registry and is therefore reported unsupported instead of invented.

    Args:
        family: Which policy family to inspect: `network`, `priority`, `nat`,
            `security`, `performance`, or `all` to query every family at
            once (each item tagged with `policy_family`). `all` only
            supports `operation="sets"` or `"stacks"` — `rules`/`status`
            need a single `policy` name, which is meaningless across
            families at once.
        operation: `sets` (default) or `stacks` list every policy set/stack
            tenant-wide, no `policy` needed. `rules` lists the rules inside
            one policy set — requires `policy`. `status` gets one policy
            set's status — requires `policy`; not available for `family="security"`
            (reported as `unsupported_operation`, not guessed).
        policy: Exact/partial policy-set name or controller ID. Required for
            `rules`/`status`, ignored for `sets`/`stacks`. Ambiguous
            partial matches are never auto-picked — the error lists every
            candidate so you can retry with an exact name or ID.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max items to return in this page. Omit to use the server
            default page size.
    """
    tool = "get_policies"
    try:
        if family == "all":
            if operation not in {"sets", "stacks"}:
                return error_json("invalid_argument", "family='all' supports only sets or stacks", tool, 400)
            combined = []
            family_errors = {}
            for current_family, current_spec in POLICY_MAP.items():
                action = current_spec.get(operation)
                if not action:
                    continue
                result = execute(action)
                if isinstance(result, dict) and "error" in result:
                    family_errors[current_family] = result["error"]
                    continue
                combined.extend({**item, "policy_family": current_family} for item in records(result))
            return collection_json(
                tool,
                f"All policy {operation}: {len(combined)} item(s) across {len(POLICY_MAP)} families",
                "items",
                combined,
                cursor=cursor,
                limit=limit,
                extra={"family": "all", "operation": operation, "family_errors": family_errors or None},
            )
        spec = POLICY_MAP[family]
        if operation in {"sets", "stacks"}:
            action = spec[operation]
            data = execute(action)
            upstream = fail_from_upstream(tool, data)
            if upstream:
                return upstream
            items = records(data)
            return collection_json(tool, f"{family} policy {operation}: {len(items)} item(s)", "items", items, cursor=cursor, limit=limit, extra={"family": family, "operation": operation})
        if not policy or not policy.strip():
            return error_json("invalid_argument", "policy name or ID is required for rules/status", tool, 400)
        action = spec.get(operation)
        if not action:
            return error_json("unsupported_operation", f"{operation} is not available for {family} policies in the registry", tool, 400)
        policy_record = resolve(spec["kind"], policy)
        policy_id = policy_record.get("id")
        if not policy_id:
            return error_json("unresolved_relationship", "resolved policy has no id", tool, 409)
        data = execute(action, {spec["id_param"]: policy_id})
        upstream = fail_from_upstream(tool, data)
        if upstream:
            return upstream
        if operation == "status":
            return single_json(tool, f"{family} policy status for '{policy}'", "status", data, extra={"policy": policy_record})
        items = records(data)
        return collection_json(tool, f"{family} policy rules for '{policy}'", "rules", items, cursor=cursor, limit=limit, extra={"policy": policy_record})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_security(
    operation: SecurityOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    application: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect security zones, application catalog/version, prefixes, and SD-WAN apps.

    Application searches are performed client-side against the registry-backed
    application catalog. Site/element names are resolved automatically for
    scoped security-zone operations.

    Args:
        operation: `zones` (all security zones, no other args needed),
            `site_zones` (requires `site`), `element_zones` (requires
            `site` and `element`), `applications` (catalog search, optional
            `application` substring filter), `application_version` (catalog
            version info, no args), `global_prefixes`/`local_prefixes`
            (no other args needed), `sdwan_apps` (list, no other args),
            `sdwan_app_status`/`sdwan_app_configs` (requires `application`
            as an exact SD-WAN app ID, not a name search).
        site: Site name or controller ID. Required for `site_zones` and
            `element_zones`; ignored otherwise.
        element: ION/element name or controller ID. Required (with `site`)
            for `element_zones`; ignored otherwise.
        application: For `operation="applications"`, an optional
            case-insensitive substring to filter the application catalog by
            display name. For `sdwan_app_status`/`sdwan_app_configs`, this
            must instead be the exact SD-WAN app controller ID (not a
            search term) — those two operations do not resolve names.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call. Has no effect when the
            result is empty — an operation with zero matches returns a
            `result` key instead of a typed collection key.
        limit: Max items to return in this page. Omit to use the server
            default page size.
    """
    tool = "get_security"
    try:
        if operation == "zones":
            data = execute("security_policies.securityzones")
        elif operation == "applications":
            data = execute("security_policies.appdefs")
            items = records(data)
            if application:
                needle = application.strip().lower()
                items = [x for x in items if needle in str(x.get("display_name") or x.get("name") or "").lower()]
            return collection_json(tool, f"Application definitions: {len(items)} match(es)", "applications", items, cursor=cursor, limit=limit, extra={"search": application})
        elif operation == "application_version":
            data = execute("security_policies.appdefs_version")
            upstream = fail_from_upstream(tool, data)
            if upstream:
                return upstream
            return single_json(tool, "Application catalog version", "version", data)
        elif operation == "global_prefixes":
            data = execute("security_policies.ngfwsecuritypolicyglobalprefixes")
        elif operation == "local_prefixes":
            data = execute("security_policies.ngfwsecuritypolicylocalprefixes")
        elif operation == "sdwan_apps":
            data = execute("security_policies.sdwanapps")
        elif operation in {"sdwan_app_status", "sdwan_app_configs"}:
            if not application or not application.strip():
                return error_json("invalid_argument", "application must identify an SD-WAN app ID for this operation", tool, 400)
            action = "security_policies.sdwanapps_status" if operation == "sdwan_app_status" else "security_policies.sdwanapps_configs"
            data = execute(action, {"sdwanapp_id": application.strip()})
        else:
            site_id, element_id, _ = site_element(site, element)
            if operation == "site_zones":
                if not site_id:
                    return error_json("invalid_argument", "site is required", tool, 400)
                data = execute("security_policies.sitesecurityzones", {"site_id": site_id})
            elif operation == "element_zones":
                if not site_id or not element_id:
                    return error_json("invalid_argument", "site and element are required", tool, 400)
                data = execute("security_policies.elementsecurityzones", {"site_id": site_id, "element_id": element_id})
            else:
                return error_json("invalid_argument", f"unsupported security operation '{operation}'", tool, 400)
        upstream = fail_from_upstream(tool, data)
        if upstream:
            return upstream
        items = records(data)
        if items:
            return collection_json(tool, f"Security operation '{operation}' returned {len(items)} item(s)", "items", items, cursor=cursor, limit=limit)
        return single_json(tool, f"Security operation '{operation}'", "result", data)
    except Exception as exc:
        return handle_error(tool, exc)
