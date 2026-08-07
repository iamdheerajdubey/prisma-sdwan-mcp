from prisma_sdwan_mcp.safety import ResponseSafety


def test_recursive_secret_redaction():
    safety = ResponseSafety()
    data = {
        "name": "vpn",
        "authentication": {
            "secret": "abc",
            "private_key": "pem",
            "passphrase_encrypted": "cipher",
            "peer_id": "peer-1",
        },
        "session_id": "sid",
        "nested": [{"snmp_community_string": "public", "state": "up"}],
    }
    redacted = safety.redact(data)
    assert redacted["name"] == "vpn"
    assert redacted["authentication"]["secret"] == "[REDACTED]"
    assert redacted["authentication"]["private_key"] == "[REDACTED]"
    assert redacted["authentication"]["passphrase_encrypted"] == "[REDACTED]"
    assert redacted["authentication"]["peer_id"] == "peer-1"
    assert redacted["session_id"] == "[REDACTED]"
    assert redacted["nested"][0]["snmp_community_string"] == "[REDACTED]"
