from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    category: str
    parameters: dict[str, Any]
    fn: Any

    @property
    def properties(self) -> dict[str, dict[str, Any]]:
        return self.parameters.get("properties") or {}

    @property
    def required(self) -> set[str]:
        return set(self.parameters.get("required") or [])


# These are intentionally broad. The catalogue is discovered at runtime and
# different provider versions may use slightly different tool names.
INTENT_RULES: dict[str, dict[str, Any]] = {
    "sites": {
        "positive": ("site", "sites", "branch"),
        "verbs": ("list", "get", "read", "inventory", "search"),
        "negative": ("template", "profile", "config", "policy", "alarm", "metric", "resolve"),
        "categories": ("inventory", "resolve"),
    },
    "devices": {
        "positive": ("device", "element", "ion", "appliance"),
        "verbs": ("list", "get", "read", "inventory", "search"),
        "negative": ("config", "template", "metric", "alarm", "resolve"),
        "categories": ("inventory", "network", "resolve"),
    },
    "alarms": {
        "positive": ("alarm", "alert", "incident", "event", "fault"),
        "verbs": ("list", "get", "read", "active", "query", "search"),
        "negative": ("config", "template", "generate"),
        "categories": ("monitoring",),
    },
    "connectivity": {
        "positive": ("wan", "path", "link", "circuit", "interface", "vpn"),
        "verbs": ("list", "get", "read", "status", "state", "inventory"),
        "negative": ("config", "template", "generate", "delete", "create"),
        "categories": ("network", "routing", "monitoring", "inventory"),
    },
    "telemetry": {
        "positive": ("metric", "telemetry", "lqm", "latency", "loss", "jitter", "utilization", "health"),
        "verbs": ("get", "query", "read", "monitor", "history", "timeseries", "statistics"),
        "negative": ("config", "template", "generate", "create", "delete"),
        "categories": ("monitoring",),
    },
    "resources": {
        "positive": ("resource", "inventory", "site", "device", "element", "wan", "path", "circuit", "interface", "vpn", "peer"),
        "verbs": ("list", "get", "read", "inventory", "resolve", "search"),
        "negative": ("config", "template", "generate", "create", "delete"),
        "categories": ("inventory", "resolve", "network", "routing"),
    },
}


def _text(tool: ToolSpec) -> str:
    return f"{tool.name} {tool.description} {tool.category}".lower().replace("_", " ").replace("-", " ")


def score_tool(tool: ToolSpec, intent: str) -> int:
    rule = INTENT_RULES[intent]
    text = _text(tool)
    score = 0

    positive_hits = 0
    for term in rule["positive"]:
        if term in text:
            score += 8
            positive_hits += 1
    if positive_hits == 0:
        return 0
    for term in rule["verbs"]:
        if term in text:
            score += 3
    for term in rule["negative"]:
        if term in text:
            score -= 9
    if tool.category.lower() in rule["categories"]:
        score += 5

    name = tool.name.lower()
    if name.startswith(("list_", "get_", "query_", "search_", "resolve_")):
        score += 3
    if name.startswith(("create_", "update_", "delete_", "generate_", "set_")):
        score -= 12

    # Prefer tools that require little context for top-level customer pages.
    score -= len(tool.required) * 2
    return score


def rank_tools(tools: Iterable[ToolSpec], intent: str) -> list[ToolSpec]:
    ranked = sorted(tools, key=lambda tool: (score_tool(tool, intent), tool.name), reverse=True)
    return [tool for tool in ranked if score_tool(tool, intent) > 0]


def safe_public_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "parameters": tool.parameters,
    }
