from __future__ import annotations

from typing import Any

from .catalog import CapabilityCatalog, RegistryError
from .executor import CapabilityExecutor
from .models import Resolution


class ResolutionError(RuntimeError):
    def __init__(self, message: str, *, candidates: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


class ResourceResolver:
    """Human-name to controller-ID resolver. It never auto-picks ambiguous matches."""

    def __init__(self, catalog: CapabilityCatalog, executor: CapabilityExecutor):
        self.catalog = catalog
        self.executor = executor

    @staticmethod
    def _records(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for key in ("items", "data", "results"):
                if isinstance(value.get(key), list):
                    return [x for x in value[key] if isinstance(x, dict)]
            if "error" not in value:
                return [value]
        return []

    @staticmethod
    def _project(item: dict[str, Any], fields: list[str] | tuple[str, ...]) -> dict[str, Any]:
        return {field: item[field] for field in fields if item.get(field) is not None}

    def find(self, kind: str, value: str, *, path_parameters: dict[str, Any] | None = None) -> Resolution:
        if not value or not value.strip():
            raise ResolutionError(f"{kind} name/ID is required")
        alias = self.catalog.resource_alias(kind)
        data = self.executor.execute(alias["action_id"], path_parameters=path_parameters)
        if isinstance(data, dict) and "error" in data:
            raise ResolutionError(f"Unable to resolve {kind}: {data['error']}")
        records = self._records(data)
        requested = value.strip()
        lower = requested.lower()
        fields = alias.get("match_fields") or ["name"]
        projection = alias.get("projection") or ["id", "name"]

        exact_id = [r for r in records if str(r.get("id", "")) == requested]
        if exact_id:
            matches = exact_id
        else:
            exact_name = [
                r for r in records
                if any(r.get(field) is not None and str(r[field]).lower() == lower for field in fields)
            ]
            if exact_name:
                matches = exact_name
            else:
                matches = [
                    r for r in records
                    if any(r.get(field) is not None and lower in str(r[field]).lower() for field in fields)
                ]
        return Resolution(kind, requested, [self._project(r, projection) for r in matches])

    def require_one(self, kind: str, value: str, *, path_parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.find(kind, value, path_parameters=path_parameters)
        if not result.matches:
            raise ResolutionError(f"No {kind} matches '{value}'")
        if len(result.matches) > 1:
            raise ResolutionError(
                f"{len(result.matches)} {kind} records match '{value}'; specify an exact name or ID",
                candidates=result.matches,
            )
        return result.matches[0]

    def site_element(self, site: str | None, element: str | None) -> tuple[str | None, str | None, dict[str, Any] | None]:
        site_record = self.require_one("site", site) if site else None
        site_id = site_record.get("id") if site_record else None
        element_record = None
        if element:
            resolution = self.find("element", element)
            matches = resolution.matches
            if site_id is not None:
                scoped = [item for item in matches if item.get("site_id") in (None, site_id)]
                # Prefer site-scoped candidates when the inventory includes site_id.
                with_site = [item for item in scoped if item.get("site_id") == site_id]
                if not scoped and matches:
                    # Every name/ID match belongs to some other site — a more specific
                    # error than "no element matches" (which would suggest a typo).
                    other_sites = sorted({str(item["site_id"]) for item in matches if item.get("site_id")})
                    requested_site = (site_record or {}).get("name") or site_id
                    raise ResolutionError(
                        f"Element '{element}' belongs to site_id "
                        f"{'/'.join(other_sites) if other_sites else 'unknown'}, not requested site '{requested_site}'"
                    )
                matches = with_site or scoped
            if not matches:
                scope = f" at site_id '{site_id}'" if site_id else ""
                raise ResolutionError(f"No element matches '{element}'{scope}")
            if len(matches) > 1:
                raise ResolutionError(
                    f"{len(matches)} element records match '{element}'" + (f" at site_id '{site_id}'" if site_id else "") + "; specify an exact ID",
                    candidates=matches,
                )
            element_record = matches[0]
        element_id = element_record.get("id") if element_record else None
        element_site = element_record.get("site_id") if element_record else None
        if site_id is None and element_site:
            site_id = element_site
        return site_id, element_id, element_record
