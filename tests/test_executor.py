from types import SimpleNamespace

import pytest

from prisma_sdwan_mcp.catalog import CapabilityCatalog
from prisma_sdwan_mcp.client import PrismaSDWANClient
from prisma_sdwan_mcp.executor import CapabilityExecutionError, CapabilityExecutor
from prisma_sdwan_mcp.safety import ResponseSafety


class GetAPI:
    def interfaces(self, site_id, element_id, api_version=None):
        return [{"id": "if1", "site_id": site_id, "element_id": element_id, "secret": "hide"}]

    def sites(self, api_version=None):
        return [{"id": "s1", "name": "Branch One"}]


class PostAPI:
    def networkcontexts_query(self, data, api_version=None):
        return [{"id": "n1", "name": data.get("name", "all") }]

    def element_extensions_query(self, data, *args, **kwargs):
        return [{"data": data, "args": list(args), "kwargs": kwargs}]


@pytest.fixture
def executor():
    sdk = SimpleNamespace(get=GetAPI(), post=PostAPI())
    client = PrismaSDWANClient(sdk=sdk)
    catalog = CapabilityCatalog()
    return CapabilityExecutor(catalog, client, ResponseSafety())


def test_get_dispatch_and_redaction(executor):
    result = executor.execute("sites_devices.interfaces", {"site_id": "s1", "element_id": "e1"})
    assert result[0]["id"] == "if1"
    assert result[0]["secret"] == "[REDACTED]"


def test_post_dispatch_by_signature(executor):
    result = executor.execute("sites_devices.networkcontexts_query", body={"name": "LAN"})
    assert result[0]["name"] == "LAN"


def test_missing_path_is_rejected(executor):
    with pytest.raises(CapabilityExecutionError):
        executor.execute("sites_devices.interfaces", {"site_id": "s1"})


def test_registry_schema_hints_are_normalized(executor):
    # A source-registry schema with property-level required:false should not be rejected as invalid JSON Schema.
    body = {"name": "LAN"}
    result = executor.execute("sites_devices.networkcontexts_query", body=body)
    assert result


def test_post_path_fallback_does_not_drop_ids(executor):
    result = executor.execute(
        "sites_devices.element_extensions_query",
        {"site_id": "s1", "element_id": "e1"},
        {"limit": 5},
    )
    assert result[0]["data"] == {"limit": 5}
    assert result[0]["args"] == ["s1", "e1"]
