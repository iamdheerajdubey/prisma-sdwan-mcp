from __future__ import annotations

from .catalog import CapabilityCatalog
from .client import PrismaSDWANClient
from .executor import CapabilityExecutor
from .resolver import ResourceResolver
from .safety import ResponseSafety

catalog = CapabilityCatalog()
safety = ResponseSafety(catalog.overrides.get("sensitive_key_patterns"))
client: PrismaSDWANClient | None = None
executor: CapabilityExecutor | None = None
resolver: ResourceResolver | None = None


def initialize(sdk=None) -> None:
    global client, executor, resolver
    client = PrismaSDWANClient(sdk=sdk)
    executor = CapabilityExecutor(catalog, client, safety)
    resolver = ResourceResolver(catalog, executor)


def ensure_initialized() -> tuple[CapabilityExecutor, ResourceResolver]:
    global executor, resolver
    if executor is None or resolver is None:
        initialize()
    assert executor is not None and resolver is not None
    return executor, resolver
