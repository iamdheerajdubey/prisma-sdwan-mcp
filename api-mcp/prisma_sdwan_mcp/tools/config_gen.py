import json
import ntpath
import os
from typing import Any, Dict, List

import jsonschema
import yaml

from .. import registry
from ..config import get_output_dir
from ..formatting import bounded_response, error_json, internal_error


mcp = registry.mcp
PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PACKAGE_DIR, "schema.json")


def _resolve_output_path(filename: str) -> tuple[str | None, str | None]:
    if not isinstance(filename, str) or not filename.strip():
        return None, "filename must be a non-empty relative filename"
    candidate = filename.strip()
    if os.path.isabs(candidate) or ntpath.isabs(candidate) or ntpath.splitdrive(candidate)[0]:
        return None, "filename must be relative to PRISMA_MCP_OUTPUT_DIR"
    parts = candidate.replace("\\", "/").split("/")
    if ".." in parts:
        return None, "filename cannot contain parent-directory traversal"
    base = os.path.realpath(os.path.abspath(get_output_dir()))
    target = os.path.realpath(os.path.join(base, candidate))
    try:
        inside_base = os.path.commonpath([base, target]) == base
    except ValueError:
        inside_base = False
    if not inside_base:
        return None, "filename resolves outside PRISMA_MCP_OUTPUT_DIR"
    return target, None


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def str_presenter(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


IndentDumper.add_representer(str, str_presenter)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
def generate_site_config(
    site_id: str,
    elements: List[Dict[str, Any]],
    filename: str = "generated_sites.prisma.yaml",
    overwrite: bool = False,
) -> str:
    """Generate a validated YAML site configuration file.

    Args:
        site_id: Site identifier.
        elements: Element definitions with serial_number and optional variables.
        filename: Output YAML filename.
        overwrite: Replace existing file when true, otherwise merge sites.

    Returns:
        JSON success or error details.

    Examples:
        - generate_site_config(site_id="BRANCH-101", elements=[])
    """
    try:
        output_path, path_error = _resolve_output_path(filename)
        if path_error:
            return error_json("invalid_filename", path_error, "generate_site_config", 400)
        if not os.path.exists(SCHEMA_PATH):
            return error_json(
                "schema_not_found",
                f"Schema file not found at {SCHEMA_PATH}",
                "generate_site_config",
                500,
            )
        with open(SCHEMA_PATH, "r", encoding="utf-8") as file:
            schema = json.load(file)

        new_site = {"site_id": site_id, "elements": []}
        for element in elements:
            element_entry = {}
            serial_number = element.get("serial_number")
            if not serial_number:
                return error_json(
                    "invalid_element",
                    "Each element must have a 'serial_number'",
                    "generate_site_config",
                    400,
                )
            element_entry["serial_number"] = serial_number
            model_name = element.get("model_name")
            if model_name:
                element_entry["model_name"] = model_name
            device_vars = element.get("device_variables", {})
            if device_vars:
                element_entry["device_variables"] = device_vars
            policy_vars = element.get("policy_variables", {})
            if policy_vars:
                element_entry["policy_variables"] = policy_vars
            new_site["elements"].append(element_entry)

        existing_config = None
        if not overwrite and os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as file:
                    existing_config = yaml.safe_load(file)
            except (OSError, yaml.YAMLError):
                existing_config = None

        if existing_config and isinstance(existing_config, dict) and "prisma_sdwan" in existing_config:
            sites = existing_config["prisma_sdwan"].get("sites", [])
            replaced = False
            for index, site in enumerate(sites):
                if site.get("site_id") == site_id:
                    sites[index] = new_site
                    replaced = True
                    break
            if not replaced:
                sites.append(new_site)
            existing_config["prisma_sdwan"]["sites"] = sites
            config = existing_config
        else:
            config = {"prisma_sdwan": {"sites": [new_site]}}

        try:
            jsonschema.validate(instance=config, schema=schema)
        except jsonschema.ValidationError as error:
            return error_json(
                "schema_validation_failed",
                str(error.message),
                "generate_site_config",
                400,
            )

        yaml_content = "---\n# Prisma SD-WAN Sites\n"
        yaml_content += yaml.dump(
            config, Dumper=IndentDumper, default_flow_style=False, sort_keys=False
        )
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(yaml_content)

        site_count = len(config["prisma_sdwan"]["sites"])
        return bounded_response(
            "generate_site_config",
            {
                "tool": "generate_site_config",
                "summary": f"Site '{site_id}' configuration written",
                "status": "success",
                "filename": output_path,
                "site_count": site_count,
                "message": f"Site '{site_id}' written to {output_path} ({site_count} total site(s)).",
                "truncated": False,
                "total_count": site_count,
                "returned_count": site_count,
            }
        )
    except Exception as error:
        return internal_error("generate_site_config", error)