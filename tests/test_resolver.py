from types import SimpleNamespace

import pytest

from prisma_sdwan_mcp.catalog import CapabilityCatalog
from prisma_sdwan_mcp.client import PrismaSDWANClient
from prisma_sdwan_mcp.executor import CapabilityExecutor
from prisma_sdwan_mcp.resolver import ResolutionError, ResourceResolver
from prisma_sdwan_mcp.safety import ResponseSafety


class GetAPI:
    def sites(self, api_version=None):
        return [
            {"id": "s1", "name": "London"},
            {"id": "s2", "name": "London-DR"},
        ]

    def elements(self, api_version=None):
        return [
            {"id": "e1", "name": "ION-1", "site_id": "s1"},
            {"id": "e2", "name": "ION-2", "site_id": "s2"},
        ]


class PostAPI:
    pass


@pytest.fixture
def resolver():
    catalog = CapabilityCatalog()
    client = PrismaSDWANClient(sdk=SimpleNamespace(get=GetAPI(), post=PostAPI()))
    return ResourceResolver(catalog, CapabilityExecutor(catalog, client, ResponseSafety()))


def test_exact_name_beats_substring_ambiguity(resolver):
    item = resolver.require_one("site", "London")
    assert item["id"] == "s1"


def test_substring_ambiguity_is_not_auto_picked(resolver):
    with pytest.raises(ResolutionError) as exc:
        resolver.require_one("site", "Lon")
    assert len(exc.value.candidates) == 2


def test_element_can_supply_site_id(resolver):
    site_id, element_id, _ = resolver.site_element(None, "ION-2")
    assert site_id == "s2"
    assert element_id == "e2"


def test_site_context_can_disambiguate_duplicate_element_names():
    class DupGetAPI(GetAPI):
        def elements(self, api_version=None):
            return [
                {"id": "e1", "name": "ION", "site_id": "s1"},
                {"id": "e2", "name": "ION", "site_id": "s2"},
            ]
    catalog = CapabilityCatalog()
    client = PrismaSDWANClient(sdk=SimpleNamespace(get=DupGetAPI(), post=PostAPI()))
    scoped = ResourceResolver(catalog, CapabilityExecutor(catalog, client, ResponseSafety()))
    site_id, element_id, _ = scoped.site_element("London", "ION")
    assert site_id == "s1"
    assert element_id == "e1"
