# Path Quality / SLA Troubleshooting

## Goal

Handle cases where interfaces and VPNs are up but users experience packet loss, high latency, jitter, poor MOS, or a performance/SLA warning.

## 1. Confirm this is a quality problem, not a hard-down problem

Before interpreting quality metrics, verify the relevant path/tunnel is administratively enabled and operationally up enough to carry traffic. If the path is hard down, diagnose the hard-down fault first.

## 2. Retrieve controller-recorded telemetry

Use:

- `get_monitoring(operation='link_metrics', site=<site>, hours=<small-window>)`
- `get_monitoring(operation='probe_metrics', site=<site>, hours=<small-window>)` when configured synthetic probes are relevant.

The MCP returns recorded telemetry; `link_metrics` includes LQM latency/loss/jitter/MOS snapshot data plus bandwidth data. Use a narrow time window first because wide metric windows can exceed response limits.

If the incident time is known, use explicit `start_time`/`end_time` around it.

## 3. Map metrics to the affected path

Use `get_wan(operation='paths', site=<site>)`, `get_topology`, and `resolve_path` as needed to map opaque metric/path IDs to the actual circuit/interface.

Never call a circuit bad when the metric cannot be mapped to that circuit.

## 4. Compare against configured policy, not invented thresholds

The SOP states that degradation occurs when latency/jitter/loss breaches thresholds in a Path Quality Profile, but it does not define universal threshold values.

Therefore:

- do not invent thresholds such as 100 ms or 1% loss;
- when the user asks whether an SLA/profile was breached, inspect the relevant performance policy with `get_policies(family='performance', ...)` or the expert capability path if the semantic policy tool cannot expose the needed rule/profile;
- if the exact policy-to-path mapping cannot be proven, report the observed metrics and say the configured threshold comparison is unresolved.

This distinction matters: "high loss observed" and "configured SLA breached" are not automatically the same claim.

## 5. Current device snapshot when useful

As supplementary current evidence, use:

- `inspect lqm stats internet`

This is useful when the user's symptom is happening now and the controller metric snapshot may lag.

Do not substitute a single current snapshot for historical incident evidence.

## 6. Correlate quality with tunnel symptoms

If BFD/tunnel flaps coexist with elevated loss/jitter:

- treat path quality as a plausible causal contributor;
- compare both directions/endpoints when data is available;
- avoid claiming causality from temporal coincidence alone if metrics are sparse.

## 7. Output expectation

Report:

- affected path/circuit;
- time window;
- latency, jitter, loss, MOS evidence actually returned;
- configured threshold/profile evidence if available;
- whether the symptom is current, historical, or both;
- likely fault domain and confidence.
