# Prisma SD-WAN Troubleshooting Agent

This folder intentionally contains no agent framework code.

The agent is composed of:

- LLM: selected by the hosting AI runtime;
- system prompt: `system_prompt.md`;
- Skill: `../skills/prisma-sdwan-tshoot/`;
- MCP: the existing `prisma-sdwan-mcp` server.

`agent.yaml` is a small implementation-neutral manifest showing how the pieces fit together. If the hosting platform uses a different manifest format, map these fields into that platform rather than adding an orchestration framework.

## Runtime flow

```text
User description
    -> system prompt + LLM
    -> prisma-sdwan-tshoot Skill
    -> Prisma SD-WAN MCP tools
    -> controller / ION evidence
    -> evidence-driven diagnosis
```

The Skill owns troubleshooting strategy and interpretation. MCP owns API/device execution, name/ID resolution, credentials, safety policy, retries, and response redaction.
