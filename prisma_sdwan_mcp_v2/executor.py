from __future__ import annotations

import inspect
from typing import Any

from jsonschema import Draft202012Validator, ValidationError, SchemaError

from .catalog import CapabilityCatalog, RegistryError
from .client import PrismaSDWANClient
from .models import ActionSpec
from .safety import ResponseSafety


class CapabilityExecutionError(RuntimeError):
    pass


_BODY_PARAMETER_NAMES = {"data", "body", "payload", "request", "request_body", "query", "query_body"}


class CapabilityExecutor:
    """Registry-driven SDK dispatcher with schema checking and universal redaction."""

    def __init__(self, catalog: CapabilityCatalog, client: PrismaSDWANClient, safety: ResponseSafety):
        self.catalog = catalog
        self.client = client
        self.safety = safety

    @staticmethod
    def _validate_paths(action: ActionSpec, supplied: dict[str, Any]) -> dict[str, Any]:
        cleaned = {str(k): v for k, v in (supplied or {}).items() if v is not None}
        missing = [name for name in action.required_path_parameters if name not in cleaned or cleaned[name] == ""]
        if missing:
            raise CapabilityExecutionError(f"Missing required path parameter(s): {', '.join(missing)}")
        allowed = {p.name for p in action.path_parameters}
        unknown = sorted(set(cleaned) - allowed)
        if unknown:
            raise CapabilityExecutionError(f"Unknown path parameter(s) for {action.action_id}: {', '.join(unknown)}")
        return cleaned

    @staticmethod
    def _normalize_schema(schema: Any) -> Any:
        # The generated registry contains useful type hints, but it is not strict
        # JSON Schema: property entries use ``required: false`` and a few SDK
        # fields use vendor types such as ``java``. Normalize those hints before
        # validation instead of rejecting a valid read-only request because the
        # source metadata is non-standard.
        if isinstance(schema, list):
            return [CapabilityExecutor._normalize_schema(x) for x in schema]
        if not isinstance(schema, dict):
            return schema
        valid_types = {"object", "array", "string", "integer", "number", "boolean", "null"}
        result: dict[str, Any] = {}
        for key, item in schema.items():
            if key == "required" and isinstance(item, bool):
                continue
            if key == "type" and isinstance(item, str) and item not in valid_types:
                continue
            if key in {"properties", "$defs", "definitions", "patternProperties"} and isinstance(item, dict):
                result[key] = {k: CapabilityExecutor._normalize_schema(v) for k, v in item.items()}
            elif key in {"items", "additionalProperties"} and isinstance(item, (dict, list)):
                result[key] = CapabilityExecutor._normalize_schema(item)
            else:
                result[key] = CapabilityExecutor._normalize_schema(item)
        return result

    @staticmethod
    def _validate_body(action: ActionSpec, body: dict[str, Any] | None) -> dict[str, Any] | None:
        if action.http_method == "GET":
            if body not in (None, {}):
                raise CapabilityExecutionError("GET capability does not accept a body")
            return None
        value = {} if body is None else body
        if not isinstance(value, dict):
            raise CapabilityExecutionError("POST body must be a JSON object")
        if action.body_schema:
            schema = CapabilityExecutor._normalize_schema(action.body_schema)
            try:
                Draft202012Validator(schema).validate(value)
            except ValidationError as exc:
                path = ".".join(str(x) for x in exc.absolute_path)
                where = f" at {path}" if path else ""
                raise CapabilityExecutionError(f"Body schema validation failed{where}: {exc.message}") from exc
            except SchemaError:
                # Registry schema hints should never make a read-only capability
                # unusable. If a future generated hint is still non-standard,
                # fall back to runtime SDK validation and record it in live QA.
                pass
        return value

    @staticmethod
    def _signature_call(method: Any, action: ActionSpec, paths: dict[str, Any], body: dict[str, Any] | None) -> tuple[list[Any], dict[str, Any]] | None:
        """Use parameter names when the generated SDK exposes a useful Python signature."""
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return None
        params = [p for p in signature.parameters.values() if p.name != "self"]
        if not params or all(p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD) for p in params):
            return None
        kwargs: dict[str, Any] = {}
        body_bound = False
        bound_paths: set[str] = set()
        for param in params:
            if param.name in paths:
                kwargs[param.name] = paths[param.name]
                bound_paths.add(param.name)
            elif action.api_version and param.name == "api_version":
                kwargs[param.name] = action.api_version
            elif body is not None and (param.name.lower() in _BODY_PARAMETER_NAMES or (action.http_method == "POST" and not body_bound and param.default is inspect.Parameter.empty)):
                kwargs[param.name] = body
                body_bound = True
        required_missing = [
            p.name
            for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            and p.default is inspect.Parameter.empty
            and p.name not in kwargs
        ]
        if required_missing:
            return None
        # If the generated method hides path IDs behind *args/**kwargs, named
        # signature binding would silently drop them. Use the positional
        # fallback candidates instead.
        if set(paths) - bound_paths:
            return None
        if action.http_method == "POST" and body is not None and not body_bound:
            return None
        return [], kwargs

    @staticmethod
    def _fallback_candidates(action: ActionSpec, paths: dict[str, Any], body: dict[str, Any] | None) -> list[tuple[list[Any], dict[str, Any]]]:
        ordered = [paths[p.name] for p in action.path_parameters if p.name in paths]
        api_kw = {"api_version": action.api_version} if action.api_version and action.source == "v1_compat" else {}
        if action.http_method == "GET":
            candidates = [(ordered, api_kw), ([], {**paths, **api_kw})]
        else:
            candidates = [
                ([body or {}, *ordered], api_kw),
                ([*ordered, body or {}], api_kw),
                ([], {**paths, "data": body or {}, **api_kw}),
            ]
        # Remove exact duplicates while preserving order.
        unique: list[tuple[list[Any], dict[str, Any]]] = []
        seen = set()
        for args, kwargs in candidates:
            marker = (repr(args), repr(sorted(kwargs.items())))
            if marker not in seen:
                unique.append((args, kwargs))
                seen.add(marker)
        return unique

    def execute(
        self,
        action_id: str,
        path_parameters: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        action = self.catalog.get(action_id)
        paths = self._validate_paths(action, path_parameters or {})
        validated_body = self._validate_body(action, body)
        namespace = getattr(self.client.sdk, action.http_method.lower(), None)
        if namespace is None:
            raise CapabilityExecutionError(f"SDK has no {action.http_method.lower()} namespace")
        method = getattr(namespace, action.sdk_call, None)
        if method is None:
            raise CapabilityExecutionError(f"SDK method not available: {action.http_method.lower()}.{action.sdk_call}")

        signature_call = self._signature_call(method, action, paths, validated_body)
        candidates = [signature_call] if signature_call is not None else self._fallback_candidates(action, paths, validated_body)
        last_type_error: str | None = None
        for args, kwargs in candidates:
            try:
                result = self.client.invoke(method, *args, **kwargs)
            except TypeError as exc:  # client.invoke normally catches SDK errors; this protects test/custom clients
                last_type_error = str(exc)
                continue
            # A plain TypeError returned by the wrapper is usually a bad invocation pattern.
            if isinstance(result, dict) and result.get("exception_type") == "TypeError" and len(candidates) > 1:
                last_type_error = result.get("error")
                continue
            return self.safety.redact(result)
        raise CapabilityExecutionError(
            f"Unable to bind SDK method {action.sdk_call} to registry parameters"
            + (f": {last_type_error}" if last_type_error else "")
        )

    def try_execute(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self.execute(*args, **kwargs)
        except (RegistryError, CapabilityExecutionError) as exc:
            return {"error": str(exc), "status_code": 400}
