import ast
from pathlib import Path

from prisma_sdwan_mcp_v2.catalog import CapabilityCatalog


def test_literal_execute_references_exist():
    catalog = CapabilityCatalog()
    root = Path(__file__).parents[1] / "prisma_sdwan_mcp_v2" / "tools"
    missing = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "execute" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value and not catalog.has(first.value):
                missing.append((path.name, node.lineno, first.value))
    assert not missing, missing


def test_all_registry_style_string_literals_reference_known_actions():
    import re
    catalog = CapabilityCatalog()
    domains = {d["domain"] for d in catalog.domains()}
    root = Path(__file__).parents[1] / "prisma_sdwan_mcp_v2" / "tools"
    missing = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if "." not in value or value.split(".", 1)[0] not in domains:
                continue
            if re.fullmatch(r"[a-z0-9_]+\.[A-Za-z0-9_]+", value) and not catalog.has(value):
                missing.append((path.name, node.lineno, value))
    assert not missing, missing
