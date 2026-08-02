## 1. Record the decision

- [x] 1.1 Adopt option (a): caller supplies target and credential on every call.
      Decided by the project owner 2026-08-02.
- [x] 1.2 Record the rejection of (c) on technical grounds (no caller identity in
      MCP, so per-element authorization is unimplementable) and the
      `--host 0.0.0.0` default caveat that compounds it.
- [x] 1.3 Record (b) as considered and not adopted, with the reasoning, so a revisit
      starts from the analysis.

## 2. Confirm the spec matches the server as built

- [x] 2.1 Walk each `cli-trust-model` requirement against the current
      `server.py` / `executor.py` / `policy.py` and confirm it describes what the
      code already does. Any requirement that does not is either a spec error or an
      undiscovered gap — resolve before archiving.
- [ ] 2.2 Confirm the audit-logging requirements reflect what is actually emitted
      today. If cli-mcp does not yet emit structured audit records, that is a real
      gap and needs its own change rather than being assumed by this one.

## 3. Do not build

- [x] 3.1 No target map, no `element_id` addressing, no server-held secret.
