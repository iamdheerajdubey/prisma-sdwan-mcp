import os
import subprocess
import sys
from pathlib import Path


def test_server_registers_expected_surface_with_dependency_stubs():
    root = Path(__file__).parents[1]
    code = r'''
import sys, types
class DummyMCP:
    def __init__(self, name): self.tools=[]; self.resources=[]; self.prompts=[]
    def tool(self, name_or_fn=None, **kwargs):
        def reg(fn): self.tools.append((kwargs.get("name", fn.__name__), fn)); return fn
        return reg(name_or_fn) if callable(name_or_fn) else reg
    def resource(self, uri, **kwargs):
        def reg(fn): self.resources.append((uri, fn)); return fn
        return reg
    def prompt(self, fn=None, **kwargs):
        def reg(f): self.prompts.append(f.__name__); return f
        return reg(fn) if callable(fn) else reg
    def run(self, **kwargs): pass
fast=types.ModuleType("fastmcp"); fast.FastMCP=DummyMCP; sys.modules["fastmcp"]=fast
class Get:
    def profile(self): return {"id":"profile"}
class API:
    def __init__(self, **kwargs):
        self.get=Get(); self.post=types.SimpleNamespace(); self.interactive=types.SimpleNamespace(login_secret=lambda **kw: {"expires_in":900})
pr=types.ModuleType("prisma_sase"); pr.API=API; sys.modules["prisma_sase"]=pr
import prisma_sdwan_mcp_v2.server as s
assert len(s.mcp.tools)==26
assert len(s.mcp.resources)==4
assert len(s.mcp.prompts)==4
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
