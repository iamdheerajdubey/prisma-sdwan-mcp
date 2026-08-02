## 1. Declare the contract

- [x] 1.1 Add a limits registry to `api-mcp/prisma_sdwan_mcp/` declaring every cap
      with its kind, value, recovery mechanism, and reason (for unrecoverable ones);
      include the cli-mcp caps by reference.
- [x] 1.2 Add the closed error-code set as a module-level constant and route
      `structured_error` through it, rejecting unknown codes in tests.
- [x] 1.3 Add `contract_version` and expose `prisma://contract` in `resources.py`,
      generated from 1.1 and 1.2 so it cannot drift.

## 2. Stop projecting diagnostic endpoints

- [x] 2.0 Pass no projection on `get_events`, `get_alarms`, `get_flows`,
      `get_interface_status`, `get_vpnlink_status`, and `get_bgp_status` so every
      upstream field reaches the consumer. Delete `EVENT_KEEP_FIELDS` and
      `FLOW_KEEP_FIELDS` rather than leaving complete-today lists in place — a frozen
      list silently drops whatever the vendor adds next release, which is the defect
      being removed.
- [x] 2.0a Re-measure response sizes afterwards: unprojected diagnostic records are
      larger, so fewer fit per page at the 40960 default. Confirm paging still
      returns everything and note the new records-per-page in the docstrings.
- [x] 2.0b Keep projections on catalogue tools (sites, elements, machines, app defs,
      policy sets, zones, path groups, service labels, WAN networks).

## 3. Close the signalling gaps

- [x] 3.1 Emit `limits_applied` from `build_envelope` whenever a cap fired; keep the
      existing booleans.
- [x] 3.2 Signal the `top_talkers` ranking limit in the flow digest.
- [x] 3.3 Signal error-message truncation in cli-mcp `_safe_error_message`.

## 4. Make caps recoverable

- [x] 4.1 Remove the `matches[:FIND_CAP]` slice in `tools/resolve.py`; verify
      `next_cursor` walks the full match set.
- [x] 4.2 Make leg resolution in `tools/network.py` resumable past
      `LEG_RESOLUTION_CAP` while keeping the per-call fan-out bound.

## 5. Add the missing error categories

- [x] 5.1 Map upstream 429 to `rate_limited` and surface retry accounting from
      `client.py`.
- [x] 5.2 Emit `partial_response` from `find_policy_set` and `get_basenet_topology`.
- [ ] 5.3 Wire `historical_data_unavailable` where a window is provably outside
      retention. `tenant_or_region_mismatch` is dropped from the code set entirely
      (owner decision 2026-08-02) — attributing a failure to tenant scope is the
      consuming agent's job, not MCP's.

## 6. Lock it with tests

- [x] 6.1 `test_formatting.py`: frozen envelope keys, `retryable` semantics, closed
      code set, full cursor-walk equality.
- [x] 6.2 One test asserting every limits-registry entry is recoverable or has a
      reason, and that every cap constant in the source has a registry entry.
- [x] 6.3 Confirm `webtester` needs no change; if it does, the change was breaking.

## 7. Verify against a live tenant (blocking before freeze)

- [x] 7.1 Diff every `*_KEEP_FIELDS` set against captured live responses; resolve the
      `src_ip`/`source_ip` and `dst_ip`/`destination_ip` aliases.
      Completed 2026-08-02 across ALL sets, in two passes — the first pass covered
      only events, flows, and elements, and was checked off prematurely. Second pass
      found two more broken lists:
      - `INTERFACE_KEEP_FIELDS`: 8 of 12 names never occur upstream
        (`ip_address`, `mac_address`, `state`, `status`, `element_id`, `site_id`,
        `interface_id`, `interface_name`). `get_interfaces` was returning only
        `id`/`name`/`type`/`admin_up` — no address, no operational state, while
        dropping `ipv4_config`, `mtu`, `used_for`, `bound_interfaces`,
        `vrf_context_id`. Resolved by removing the projection: interfaces are
        diagnostic evidence. 29 fields now reach the consumer.
      - `SITE_KEEP_FIELDS`: `city`/`country`/`latitude`/`longitude` never occur
        (real data is `address`/`location`), and all four `*_policysetstack_id`
        bindings were being dropped. Rewritten and re-verified.
      - `MACHINE_KEEP_FIELDS` and `WAN_INTERFACE_KEEP_FIELDS` were clean;
        `description` added to the latter. Machines deliberately continues to drop
        the upstream `token` field.
      All surviving projections re-verified: zero phantom fields remain.
- [x] 7.2 Determine whether the controller distinguishes wrong-tenant from
      nonexistent; drop `tenant_or_region_mismatch` if it does not.
- [x] 7.3 Determine whether path-quality/SLA thresholds are joinable from
      `site_id` + `path_id`, and whether operational HA role is exposed at all.
