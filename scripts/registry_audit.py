#!/usr/bin/env python3
from __future__ import annotations

import json

from prisma_sdwan_mcp.catalog import CapabilityCatalog
from prisma_sdwan_mcp.safety import ResponseSafety


def walk_fields(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path
            yield from walk_fields(item, path)
    elif isinstance(value, list):
        for item in value:
            yield from walk_fields(item, prefix)


def main():
    catalog = CapabilityCatalog()
    safety = ResponseSafety(catalog.overrides.get("sensitive_key_patterns"))
    sensitive = []
    unknown_urls = []
    for action in catalog.actions():
        if action.source != "registry":
            continue
        if action.url_template and "unknown_" in action.url_template:
            unknown_urls.append(action.action_id)
        for field in action.output_fields:
            if safety.is_sensitive_key(field):
                sensitive.append((action.action_id, field))
        if action.body_schema:
            for path in walk_fields(action.body_schema):
                if safety.is_sensitive_key(path.rsplit(".", 1)[-1]):
                    sensitive.append((action.action_id, path))
    print(json.dumps({
        "registry_actions": catalog.registry_action_count,
        "compat_actions": catalog.compat_action_count,
        "domains": catalog.domains(),
        "actions_with_unknown_url_placeholder": sorted(unknown_urls),
        "sensitive_schema_references": sorted(set(sensitive)),
    }, indent=2))


if __name__ == "__main__":
    main()
