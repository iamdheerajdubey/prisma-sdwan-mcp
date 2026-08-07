# Registry Notes

Source: `mcp_registry_get_post.json`.

- 18 generated domains.
- 308 generated read-only actions.
- V2 adds 8 read-only v1 compatibility actions, giving 316 executable catalog entries.
- Registry API version and SDK call data are used by the generic executor.
- The monitoring/AIOps URL templates contain an `unknown_1` placeholder in the generated source. V2 uses the verified SDK call rather than constructing raw URLs from that placeholder.
- Some resources appear in more than one logical domain (for example element users). Stable `action_id` values keep them distinct.
- Some source body schemas contain non-standard JSON-Schema hints (`required: false` inside field definitions and vendor type labels). V2 normalizes those hints before validation.
- The registry exposes fields that can contain secrets. V2 therefore treats central redaction as mandatory, not optional.
