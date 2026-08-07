from __future__ import annotations

import json
import ntpath
import os
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from ..config import data_dir, get_output_dir
from ..mcp import mcp
from ..response import error_json, single_json

LOCAL_WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

SCHEMA_PATH = data_dir() / "site_config_schema.json"


def _safe_output(filename: str) -> tuple[Path | None, str | None]:
    if not isinstance(filename, str) or not filename.strip():
        return None, "filename must be a non-empty relative filename"
    candidate = filename.strip()
    if os.path.isabs(candidate) or ntpath.isabs(candidate) or ntpath.splitdrive(candidate)[0]:
        return None, "filename must be relative to PRISMA_MCP_OUTPUT_DIR"
    parts = candidate.replace("\\", "/").split("/")
    if ".." in parts:
        return None, "filename cannot contain parent-directory traversal"
    base = get_output_dir().resolve()
    target = (base / candidate).resolve()
    try:
        if os.path.commonpath([str(base), str(target)]) != str(base):
            return None, "filename resolves outside PRISMA_MCP_OUTPUT_DIR"
    except ValueError:
        return None, "filename resolves outside PRISMA_MCP_OUTPUT_DIR"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, None


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


IndentDumper.add_representer(str, _str_presenter)


@mcp.tool(annotations=LOCAL_WRITE)
def generate_site_config(
    site_id: str,
    elements: list[dict[str, Any]],
    filename: str = "generated_sites.prisma.yaml",
    overwrite: bool = False,
) -> str:
    """Generate a validated local YAML site file for downstream automation.

    This tool writes only to ``PRISMA_MCP_OUTPUT_DIR``. It does **not** change
    Prisma SD-WAN. It is retained from v1 because it cleanly separates AI
    planning/data gathering from the mutation path; actual network changes can
    remain under Ansible/change-control.
    """
    tool = "generate_site_config"
    try:
        if not site_id or not site_id.strip():
            return error_json("invalid_argument", "site_id is required", tool, 400)
        target, path_error = _safe_output(filename)
        if path_error or target is None:
            return error_json("invalid_filename", path_error or "invalid filename", tool, 400)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        new_site = {"site_id": site_id.strip(), "elements": []}
        for element in elements:
            if not isinstance(element, dict) or not element.get("serial_number"):
                return error_json("invalid_element", "each element must contain serial_number", tool, 400)
            row = {"serial_number": element["serial_number"]}
            for key in ("model_name", "device_variables", "policy_variables"):
                if element.get(key):
                    row[key] = element[key]
            new_site["elements"].append(row)

        existing = None
        if target.exists() and not overwrite:
            try:
                existing = yaml.safe_load(target.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                existing = None
        if isinstance(existing, dict) and isinstance(existing.get("prisma_sdwan"), dict):
            sites = existing["prisma_sdwan"].setdefault("sites", [])
            for idx, item in enumerate(sites):
                if isinstance(item, dict) and item.get("site_id") == new_site["site_id"]:
                    sites[idx] = new_site
                    break
            else:
                sites.append(new_site)
            config = existing
        else:
            config = {"prisma_sdwan": {"sites": [new_site]}}
        try:
            jsonschema.validate(config, schema)
        except jsonschema.ValidationError as exc:
            return error_json("schema_validation_failed", exc.message, tool, 400)
        content = "---\n# Prisma SD-WAN Sites\n" + yaml.dump(config, Dumper=IndentDumper, default_flow_style=False, sort_keys=False)
        target.write_text(content, encoding="utf-8")
        return single_json(tool, f"Site '{site_id}' configuration written locally", "result", {"filename": str(target), "site_count": len(config["prisma_sdwan"]["sites"]), "network_changed": False})
    except Exception as exc:
        return error_json("internal_error", "failed to generate local site configuration", tool, 500, {"exception": type(exc).__name__})
