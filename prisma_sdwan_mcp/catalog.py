from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import data_dir
from .models import ActionSpec, ParameterSpec


class RegistryError(RuntimeError):
    pass


def _parameter(item: dict[str, Any]) -> ParameterSpec:
    return ParameterSpec(
        name=str(item.get("name", "")).strip(),
        required=bool(item.get("required", False)),
        type=item.get("type"),
        description=item.get("description"),
        default=item.get("default"),
    )


def _action_from_registry(domain: str, item: dict[str, Any]) -> ActionSpec:
    return ActionSpec(
        action_id=item["action_id"],
        domain=domain,
        sdk_call=item["sdk_call"],
        http_method=str(item["http_method"]).upper(),
        api_version=item.get("api_version"),
        description=item.get("description", ""),
        url_template=item.get("url_template"),
        path_parameters=tuple(_parameter(p) for p in item.get("path_parameters") or []),
        query_parameters=tuple(_parameter(p) for p in item.get("query_parameters") or []),
        body_schema=item.get("body_schema"),
        output_fields=tuple(item.get("output_fields") or []),
        source="registry",
        requires_live_test=bool(item.get("requires_live_test", False)),
    )


def _action_from_compat(item: dict[str, Any]) -> ActionSpec:
    return ActionSpec(
        action_id=item["action_id"],
        domain=item.get("domain", "curated"),
        sdk_call=item["sdk_call"],
        http_method=str(item["http_method"]).upper(),
        api_version=item.get("api_version"),
        description=item.get("description", ""),
        path_parameters=tuple(_parameter(p) for p in item.get("path_parameters") or []),
        body_schema=item.get("body_schema"),
        output_fields=tuple(item.get("output_fields") or []),
        source="curated",
        requires_live_test=bool(item.get("requires_live_test", True)),
    )


class CapabilityCatalog:
    """Validated in-memory view of the registry plus a small curated overlay for registry gaps."""

    def __init__(
        self,
        registry_path: Path | None = None,
        compat_path: Path | None = None,
        overrides_path: Path | None = None,
    ):
        base = data_dir()
        self.registry_path = registry_path or base / "mcp_registry_get_post.json"
        self.compat_path = compat_path or base / "curated_capabilities.json"
        self.overrides_path = overrides_path or base / "registry_overrides.yaml"
        self._actions: dict[str, ActionSpec] = {}
        self._domains: dict[str, dict[str, Any]] = {}
        self._overrides: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RegistryError(f"Unable to load registry: {exc}") from exc
        if not isinstance(registry.get("domains"), list):
            raise RegistryError("Registry has no domains list")

        for domain in registry["domains"]:
            name = domain.get("domain")
            if not name:
                raise RegistryError("Registry domain is missing its name")
            self._domains[name] = {
                "domain": name,
                "title": domain.get("title", name),
                "description": domain.get("description", ""),
            }
            for raw in domain.get("actions") or []:
                action = _action_from_registry(name, raw)
                self._add(action)

        if self.compat_path.exists():
            compat = json.loads(self.compat_path.read_text(encoding="utf-8"))
            self._domains.setdefault(
                "curated",
                {
                    "domain": "curated",
                    "title": "Curated Additions",
                    "description": "Read-only capabilities that fill gaps in the generated registry, added by hand.",
                },
            )
            for raw in compat.get("actions") or []:
                self._add(_action_from_compat(raw))

        if self.overrides_path.exists():
            self._overrides = yaml.safe_load(self.overrides_path.read_text(encoding="utf-8")) or {}
        self.validate()

    def _add(self, action: ActionSpec) -> None:
        if action.action_id in self._actions:
            raise RegistryError(f"Duplicate action_id: {action.action_id}")
        self._actions[action.action_id] = action

    def validate(self) -> None:
        for action in self._actions.values():
            if not action.action_id or "." not in action.action_id:
                raise RegistryError(f"Invalid action_id: {action.action_id!r}")
            if not action.sdk_call:
                raise RegistryError(f"{action.action_id}: sdk_call is missing")
            if action.http_method not in {"GET", "POST"}:
                raise RegistryError(f"{action.action_id}: only read-only GET/POST actions are supported")
            names = [p.name for p in action.path_parameters]
            if any(not name for name in names) or len(names) != len(set(names)):
                raise RegistryError(f"{action.action_id}: invalid/duplicate path parameter")

    @property
    def overrides(self) -> dict[str, Any]:
        return self._overrides

    @property
    def action_count(self) -> int:
        return len(self._actions)

    @property
    def registry_action_count(self) -> int:
        return sum(1 for action in self._actions.values() if action.source == "registry")

    @property
    def compat_action_count(self) -> int:
        return sum(1 for action in self._actions.values() if action.source == "curated")

    def get(self, action_id: str) -> ActionSpec:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise RegistryError(f"Unknown capability: {action_id}") from exc

    def has(self, action_id: str) -> bool:
        return action_id in self._actions

    def actions(self, domain: str | None = None) -> Iterable[ActionSpec]:
        values = self._actions.values()
        if domain is None:
            return tuple(values)
        return tuple(a for a in values if a.domain == domain)

    def domains(self) -> list[dict[str, Any]]:
        result = []
        for name, info in self._domains.items():
            result.append({**info, "action_count": sum(1 for a in self._actions.values() if a.domain == name)})
        return sorted(result, key=lambda x: x["domain"])

    def list_actions(self, domain: str, method: str | None = None) -> list[dict[str, Any]]:
        if domain not in self._domains:
            raise RegistryError(f"Unknown domain: {domain}")
        method_value = method.upper() if method else None
        matches = [
            self.describe(action.action_id)
            for action in self._actions.values()
            if action.domain == domain and (method_value is None or action.http_method == method_value)
        ]
        matches.sort(key=lambda m: m["action_id"])
        return matches

    def describe(self, action_id: str) -> dict[str, Any]:
        action = self.get(action_id)
        return {
            "action_id": action.action_id,
            "domain": action.domain,
            "description": action.description,
            "http_method": action.http_method,
            "sdk_call": action.sdk_call,
            "api_version": action.api_version,
            "path_parameters": [asdict(p) for p in action.path_parameters],
            "body_schema": action.body_schema,
            "output_fields": list(action.output_fields),
            "source": action.source,
            "requires_live_test": action.requires_live_test,
        }

    def resource_alias(self, kind: str) -> dict[str, Any]:
        aliases = self._overrides.get("resource_aliases") or {}
        try:
            return aliases[kind]
        except KeyError as exc:
            raise RegistryError(f"Unsupported resource kind: {kind}") from exc

    def resource_kinds(self) -> list[str]:
        return sorted((self._overrides.get("resource_aliases") or {}).keys())

    def expert_blocked(self, action_id: str) -> bool:
        return action_id in set(self._overrides.get("expert_blocked_by_default") or [])
