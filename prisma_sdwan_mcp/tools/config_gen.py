from __future__ import annotations

import json
from typing import Any

import jsonschema
import yaml

from ..config import data_dir
from ..mcp import mcp
from ..response import error_json, single_json

# No file I/O, no live Prisma API call — pure local validation/formatting.
LOCAL_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

SCHEMA_PATH = data_dir() / "site_config_schema.json"


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


IndentDumper.add_representer(str, _str_presenter)


@mcp.tool(annotations=LOCAL_ONLY)
def generate_site_config(site_id: str, elements: list[dict[str, Any]]) -> str:
    """Build and validate one site's Prisma SD-WAN config fragment.

    Structures and validates a single site's device list against the
    ``prisma_sdwan.sites`` schema used by downstream automation (e.g.
    Ansible), then returns both the structured object and ready-to-save
    YAML text. This tool never writes to disk and never calls the Prisma
    SASE API — saving the returned data to a file, combining it with other
    sites, and applying it to the network is entirely up to the caller.

    Args:
        site_id: Site identifier for the config (e.g. ``"BRANCH-101"``).
            Free text — not resolved against the live tenant, so a typo
            will not be caught here.
        elements: Non-empty list of element objects, each requiring
            ``serial_number`` (string). Optional per-element keys:
            ``model_name``, ``device_variables`` (object), ``policy_variables``
            (object). Any other key is silently dropped, not an error.
    """
    tool = "generate_site_config"
    try:
        if not site_id or not site_id.strip():
            return error_json("invalid_argument", "site_id is required", tool, 400)
        if not isinstance(elements, list) or not elements:
            return error_json("invalid_argument", "elements must be a non-empty list", tool, 400)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        new_site: dict[str, Any] = {"site_id": site_id.strip(), "elements": []}
        for element in elements:
            if not isinstance(element, dict) or not element.get("serial_number"):
                return error_json("invalid_element", "each element must contain serial_number", tool, 400)
            row = {"serial_number": element["serial_number"]}
            for key in ("model_name", "device_variables", "policy_variables"):
                if element.get(key):
                    row[key] = element[key]
            new_site["elements"].append(row)

        config = {"prisma_sdwan": {"sites": [new_site]}}
        try:
            jsonschema.validate(config, schema)
        except jsonschema.ValidationError as exc:
            return error_json("schema_validation_failed", exc.message, tool, 400)
        yaml_text = "---\n# Prisma SD-WAN Sites\n" + yaml.dump(
            config, Dumper=IndentDumper, default_flow_style=False, sort_keys=False
        )
        return single_json(
            tool,
            f"Site '{site_id}' configuration validated",
            "result",
            {"config": config, "yaml": yaml_text, "network_changed": False},
        )
    except Exception as exc:
        return error_json("internal_error", "failed to generate site configuration", tool, 500, {"exception": type(exc).__name__})
