# Live verification: are the 106 curated POST actions actually read-only?

Answers design.md Open Question 2 and tasks.md 5.3. **Result: yes — 106/106 executed
against the live tenant with no detectable server-side state change.**

Reproduce with `verification/verify_post_readonly.py`; raw output in
`verification/post-readonly-report.json`.

## Test target

| | |
|---|---|
| Tenant | TSG `1034038732`, `api.sase.paloaltonetworks.com` |
| Site | `SITE-TESTING-SPARE` (`1730487989790018996`), `admin_state: disabled` |
| Element | `SPARE-1-TESTING` (`1730487439698012496`), `connected: false` — ION powered down |
| Credentials | `PAN_*` from `.env` (read-only service account) |
| Date | 2026-08-05 |

Three of the 106 actions take a path parameter (`element_extensions_query`,
`site_extensions_query`, `site_spokeclusters_query`) and were pointed at that site
and element. The other 103 are tenant-scoped — there is no site/element to aim them
at, so they necessarily ran against the whole tenant. Each was sent a minimal query
body (`{"limit": 1}` plus any registry-declared `example_value`).

## Detector

The ideal detector is the controller audit log, but **this service account gets `403`
on both `GET /auditlog` and `POST /auditlog/query`** — recorded here so nobody plans a
future check around it.

Used instead: **`_etag` / `_updated_on_utc` drift**. Prisma SD-WAN bumps both on any
write to an object, and neither moves on a read. The run snapshots every registry GET
collection callable without arguments (99 of the 203 GET actions) and keeps only
`id → (_etag, _updated_on_utc)` per record, so ordinary telemetry churn (counters,
connectivity, timestamps) cannot register as a false positive.

Two windows, one control and one treatment, so natural drift is measured rather
than assumed:

```
snapshot A ──── (control: only GETs) ──── snapshot B
snapshot B ──── (treatment: 106 POSTs) ── snapshot C
```

## Result

| Measure | Value |
|---|---|
| Actions executed | 106 / 106 |
| HTTP 2xx | 106 |
| HTTP errors / exceptions | 0 |
| Collections snapshotted | 99 |
| Control-window changes (A→B) | **0** |
| Treatment-window changes (B→C) | **0** |
| Suspect writes | **0** |

64 of the 106 returned data (`total_count > 0`); 42 returned empty collections —
empty because this tenant has no such objects configured, not because the call failed.

## Corroborating evidence

1. **Structural** — all 106 `url_template`s end in `/query` or `/rquery`, the
   Prisma SD-WAN search idiom. No `POST` to a bare collection path (which would be a
   create), no `/operations`, no state-changing verb anywhere in the set.
2. **SDK self-description** — every `sdk_call` resolves on `prisma_sase 6.8.1b1`'s
   `sdk.post` namespace (106/106) and its generated docstring reads as a read
   ("Queries db for limit number of …", "Query and get …", "Get files and folders in …").
3. **Behavioural** — the differential above.

## Limits of this result — read before trusting it

- **Absence of an `_etag` bump is not proof of zero side effect.** A write to
  something with no `_etag` — a server-side saved search, a rate-limit counter, an
  internal access log — would not show up. With the audit log at `403` there is no
  way to close that gap from this account. What is ruled out is any mutation of a
  configuration or status object readable through the 99 snapshotted collections.
- **One tenant, one point in time.** A future `prisma_sase` release could repoint an
  `sdk_call`; the startup safety gate (spec: unresolvable `sdk_call` is excluded)
  is what defends against that, not this run.
- **103 of the 106 are tenant-scoped.** Using the disabled test site limited blast
  radius for the 3 that accept a path parameter; it could not scope the rest.
- **Bodies were minimal.** Each action was called with a near-empty query. An action
  that only mutates when given a specific field combination would not be caught.

## Verdict

The registry's `safety: {read_only: true, destructive: false, verified_working: true}`
block on the POST set is **supported by evidence**, not just asserted. design.md's
risk "a POST action's read_only classification could be wrong" is discharged for
these 106 actions as they exist today. It remains live for any action added to the
registry later, which is why the startup safety gate stays a requirement rather than
being replaced by this one-time audit.
