from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    required: bool = False
    type: str | None = None
    description: str | None = None
    default: Any = None


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    domain: str
    sdk_call: str
    http_method: str
    api_version: str | None
    description: str
    url_template: str | None = None
    path_parameters: tuple[ParameterSpec, ...] = field(default_factory=tuple)
    query_parameters: tuple[ParameterSpec, ...] = field(default_factory=tuple)
    body_schema: dict[str, Any] | None = None
    output_fields: tuple[str, ...] = field(default_factory=tuple)
    source: str = "registry"
    requires_live_test: bool = False

    @property
    def required_path_parameters(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.path_parameters if p.required)


@dataclass
class Resolution:
    kind: str
    requested: str
    matches: list[dict[str, Any]]

    @property
    def found(self) -> bool:
        return len(self.matches) == 1

    @property
    def ambiguous(self) -> bool:
        return len(self.matches) > 1

    @property
    def item(self) -> dict[str, Any] | None:
        return self.matches[0] if self.found else None
