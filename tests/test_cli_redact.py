"""Text-level redaction of device CLI output.

safety.py redacts by dict key. CLI output is one text blob under the key
"output", which is not a sensitive name, so the recursive redactor descends to
the string and returns it unchanged -- verified below, not assumed. Anything
in that text has to be matched to be caught.
"""

from __future__ import annotations

import pytest

from prisma_sdwan_mcp.cli.redact import MARKER, redact_text
from prisma_sdwan_mcp.safety import ResponseSafety


def test_the_key_based_redactor_cannot_reach_text_at_all():
    """The gap this module exists to close, stated as a test."""
    payload = {"output": "snmp-server community public RO\npassword: hunter2"}

    assert ResponseSafety().redact(payload) == payload, (
        "if this ever fails, safety.py grew text handling and this module may "
        "be redundant"
    )


@pytest.mark.parametrize(
    "line, secret",
    [
        ("snmp-server community public RO", "public"),
        ("radius-server key s3cr3t-value", "s3cr3t-value"),
        ("tacacs-server key abc123xyz", "abc123xyz"),
        ("password: hunter2", "hunter2"),
        ("passwd = correcthorse", "correcthorse"),
        ("secret 5 $1$abc$defghijklmnop", "$1$abc$defghijklmnop"),
        ("pre-shared-key: myPSKvalue", "myPSKvalue"),
        ("api-key = AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ("token: eyJhbGciOiJIUzI1NiJ9", "eyJhbGciOiJIUzI1NiJ9"),
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("community = privatestring", "privatestring"),
        ("https://admin:s3cretpw@controller.example.net", "s3cretpw"),
    ],
)
def test_each_pattern_removes_the_value(line, secret):
    redacted, changed = redact_text(line)

    assert changed is True
    assert secret not in redacted
    assert MARKER in redacted


def test_the_surrounding_line_stays_readable():
    redacted, _ = redact_text("snmp-server community public RO")

    assert redacted.startswith("snmp-server community ")
    assert redacted.endswith(" RO"), "only the value is replaced, not the line"


def test_a_pem_block_goes_entirely():
    text = (
        "key-material:\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAxyz\nabcdef\n"
        "-----END RSA PRIVATE KEY-----\n"
        "done\n"
    )
    redacted, changed = redact_text(text)

    assert changed is True
    assert "MIIEowIBAAKCAQEAxyz" not in redacted
    assert "BEGIN RSA PRIVATE KEY" not in redacted
    assert "done" in redacted


def test_ordinary_ion_output_is_left_alone():
    """Captured shape from a live ion 1200. Over-redaction is a real cost:
    an operator reading [REDACTED] where a hostname should be learns nothing."""
    output = (
        "Software\t\t\t: 6.3.6-b9\n"
        "Hardware Model\t\t\t: ion 1200-s-c5g-ww\n"
        "Uptime\t\t\t\t: 886h11m0.14s\n"
        "Element ID\t\t\t: 1743451497200008896\n"
        "Role\t\t\t\t: SPOKE\n"
        "Controller Connection\t\t: Up [CIC]\n"
        "Controller\t\t\t: controller.hood.cgnx.net [54.70.168.33]\n"
    )
    redacted, changed = redact_text(output)

    assert changed is False
    assert redacted == output


def test_empty_output_reports_no_change():
    assert redact_text("") == ("", False)


def test_a_fully_redacted_line_is_distinguishable_from_empty():
    redacted, changed = redact_text("password: hunter2")

    assert changed is True
    assert redacted != ""
    assert MARKER in redacted
