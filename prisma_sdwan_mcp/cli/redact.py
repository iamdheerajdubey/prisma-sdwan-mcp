"""Text-level secret redaction for device CLI output.

`safety.py` redacts by dict key: it walks a structure and replaces the value
of anything named like a password. That is the right shape for the controller
API, whose responses are JSON, and it is structurally incapable of helping
here. CLI output arrives as one text blob under the key ``output``, which is
not a sensitive name, so the recursive redactor descends to the string and
returns it untouched::

    ResponseSafety().redact({"output": "snmp-server community public RO"})
    -> unchanged

Verified, not assumed. Nothing keys on a secret sitting in free text; it has to
be matched.

Scope, honestly stated: a live sweep of an ion 1200 found no credential
material in the permitted `dump`/`inspect` families, and the device answered
"unknown keyword" to snmp, users, authentication and ipsec -- an ION is
controller-managed, so its secrets largely are not on the device CLI at all.
This closes a real hole with a low measured exposure on that platform. Another
firmware, another platform, or a future command need not be so tidy, and the
cost of being wrong is a credential in a transcript.

A redactor is a filter, not a proof. These patterns cover what was anticipated;
output shaped in a way nobody predicted will pass through. That is why the
command policy is an allowlist rather than an attempt to enumerate danger.
"""

from __future__ import annotations

import re

MARKER = "[REDACTED]"

# Checked first so its body cannot trip the narrower patterns below.
_PEM_BLOCK = re.compile(
    r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
    re.DOTALL,
)

# Unix-style password hashes, wherever they appear.
_HASH = re.compile(r"\$[0-9a-z]{1,2}\$[^\s:,]{4,}")

# `keyword <optional type digit> VALUE`. Not anchored to the start of a line:
# a device error can echo a fragment of configuration mid-sentence. Only the
# value is replaced, so the surrounding text stays readable and the caller can
# still see that a setting exists.
_ASSIGNMENTS = (
    re.compile(r"(?i)\b(snmp[- ]?server\s+community\s+)(\S+)"),
    re.compile(r"(?i)\b((?:radius|tacacs)[- ]?server\s+key\s+)(\S+)"),
    re.compile(r"(?i)\b(community\s*[=:]\s*)(\S+)"),
    re.compile(r"(?i)\b((?:password|passwd|secret|pre-?shared-?key|psk|auth[- ]?key|"
               r"api[- ]?key|token|passphrase)\s*[=:]\s*)(\S+)"),
    re.compile(r"(?i)\b((?:password|passwd|secret|pre-?shared-?key|psk)\s+(?:\d+\s+)?)(\S+)"),
    re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._\-]{8,})"),
)

# Credentials embedded in a URL: scheme://user:secret@host
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^/\s:@]+:)([^/\s@]+)(@)")


def redact_text(text: str) -> tuple[str, bool]:
    """Redact credential material from CLI text.

    Returns ``(text, changed)``. ``changed`` is what lets a caller tell "there
    was nothing here" from "there was something here and it is hidden": an
    empty result stays empty and reports False, while a line reduced to its
    marker reports True.
    """
    if not text:
        return text, False

    redacted = _PEM_BLOCK.sub(MARKER, text)
    redacted = _HASH.sub(MARKER, redacted)
    redacted = _URL_CREDENTIALS.sub(lambda m: m.group(1) + MARKER + m.group(3), redacted)
    for pattern in _ASSIGNMENTS:
        redacted = pattern.sub(lambda m: m.group(1) + MARKER, redacted)

    return redacted, redacted != text
