# MCP v2 Build Report

## Delivered

- Registry-first Prisma SD-WAN MCP v2 codebase.
- 26 AI-visible tools.
- 308 source-registry actions loaded unchanged.
- 8 hand-curated actions represented explicitly in a separate overlay (registry gap-fill).
- Central name/ID resolution with no ambiguous auto-selection.
- Generic GET/POST SDK dispatcher driven by registry metadata.
- Recursive secret redaction for all registry responses.
- Cursor pagination and response byte guardrails.
- Resilient auth refresh and bounded transient retries.
- Derived basenet topology workflow.
- Composite BGP status with optional prefix-health enrichment.
- Event/alarm, flow digest, link metric, and probe metric workflows.
- Policy/security/WAN/routing/diagnostic/domain tools spanning all registry domains.
- Local-only validated site YAML generator for downstream automation.
- MCP resources and troubleshooting prompts.
- Docker, editable install, wheel packaging, tests, and live validation guide.

## Build-time validation performed

```text
Python compileall: PASS
pytest: PASS (19 tests)
Wheel build: PASS
Static MCP registration with dependency stubs: PASS
  tools: 26
  resources: 5
  prompts: 4
Registry source actions: 308
Curated compatibility actions: 8
Registry URL entries with generated unknown placeholder: 11
Sensitive schema/output references detected by audit: 15
```

## Runtime validation not possible in this build container

The container does not have the vendor SDK/FastMCP installed and outbound package DNS/network access is disabled. A dependency install attempt therefore could not fetch:

- `fastmcp==3.4.4`
- `prisma_sase==6.8.1b1`

There is also no access to your live Prisma SD-WAN tenant.

Follow `docs/LIVE_VALIDATION.md` before production cutover. It specifically covers the 8 curated compatibility calls, representative registry-domain calls, and secret-redaction checks.
