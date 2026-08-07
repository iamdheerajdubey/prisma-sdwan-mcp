# V1 -> V2 Inheritance

## Kept from v1

| V1 behavior | V2 implementation |
|---|---|
| Full tool descriptions reach AI | `mcp.py` full-docstring registration wrapper |
| Auth/token refresh | `client.py` |
| 401/403 re-auth | `client.py` |
| 429/5xx bounded retry | `client.py` |
| Compact JSON | `response.py` |
| Cursor pagination | `response.py` |
| Response byte budget | `response.py` |
| Name -> ID lookup | `resolver.py` |
| Never auto-pick ambiguous names | `resolver.py` + discovery tools |
| Path-ID interpretation | `resolve_path` |
| Composite routing/health workflows | semantic tools |
| Local validated site YAML generation | `generate_site_config` |
| Workflow prompts | `prompts.py` |
| Resources call the same tool logic | `resources.py` |

## Replaced from v1

### V1

```text
MCP tool -> hard-coded sdk.get/sdk.post method
```

### V2

```text
MCP tool -> action_id -> CapabilityExecutor -> registry -> SDK
```

This is the primary long-term improvement. New read-only API coverage can usually be added to the registry without writing a new Python endpoint wrapper.

## Intentionally not copied

- Hundreds of one-endpoint tools.
- Silent assumptions about IDs.
- Raw responses with no central secret policy.
- API/SDK names as the primary AI-facing language.
