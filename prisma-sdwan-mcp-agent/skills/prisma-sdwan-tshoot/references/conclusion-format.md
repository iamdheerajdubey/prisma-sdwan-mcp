# Conclusion Format

## Default response

Keep the final user-facing answer concise and evidence-led. Use this structure unless the user asks for raw detail.

### Diagnosis

State the most specific supported conclusion in one or two sentences.

Examples of useful specificity:

- "Endpoint B DIA underlay is failing at L2; the AnyNet tunnel loss is a downstream effect."
- "Both IONs lost controller connectivity immediately after power-loss events; site power/device power is the likely fault domain."
- "Underlay and controller transport are healthy; the failing VPN leg reports BFD liveliness failure."

Avoid non-diagnoses such as "tunnel issue", "complex issue", or "N/A".

### Affected scope

Identify site(s), ION(s), circuit/path, AnyNet link, or VPN leg only when resolved.

### Evidence

List only load-bearing observations, preferably 3-6 bullets. Include timestamps for incident-history evidence when available.

Keep facts separate from inference.

### Confidence

Use `High`, `Medium`, or `Low` with a short reason when useful.

### Recommended action

Recommend the next operational action that follows from the fault domain. Examples:

- check local power/device power with site contact;
- escalate the mapped circuit/handoff to the ISP with ARP/probe evidence;
- review intentional administrative state/change history;
- investigate key/control-plane synchronization;
- investigate overlay/BFD after underlay has been eliminated.

Do not say "route ticket", "attach to ticket", "update ServiceNow", or otherwise reintroduce ITSM workflow.

## If root cause is not yet supported

Use:

### Current finding

State what has been eliminated and what remains.

### Confirmed evidence

List facts.

### Remaining hypotheses

List only plausible remaining fault domains.

### Next best check

Name one highest-value missing check and why it discriminates the remaining hypotheses.

Do not hide uncertainty behind generic language.

## Raw evidence

Provide raw CLI/API output only when the user asks or when a short excerpt is essential to support the diagnosis. Prefer parsed fields and interpretation by default.
