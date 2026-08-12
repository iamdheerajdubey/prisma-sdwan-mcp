import ast
from pathlib import Path


def test_ai_tool_surface_is_intentionally_27():
    root = Path(__file__).parents[1] / "prisma_sdwan_mcp" / "tools"
    names = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "tool":
                    names.append(node.name)
    assert len(names) == 27, sorted(names)
    assert len(names) == len(set(names))
    assert "read_capability" in names
    assert "generate_site_config" in names
    assert "run_commands" in names
