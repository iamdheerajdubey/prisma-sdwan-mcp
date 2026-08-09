import pytest

from prisma_sdwan_mcp.cli.policy import validate_batch, validate_command


@pytest.mark.parametrize(
    "command",
    [
        "dump interface status all",
        "dump interface status interface=controller1",
        "dump routing summary",
        "inspect system arp all",
        "inspect wanpaths site-id=1684490871652002728",
        "dump interface status all | grep -i MAC Address",
        "inspect system arp all | grep -F incomplete",
        # not individually enumerated -- allowed because the whole dump/
        # inspect family is trusted per docs/ION_CLI_RESEARCH.md, not because
        # this exact subcommand is listed anywhere
        "dump some-future-subcommand-not-in-any-list",
        "inspect another-future-subcommand",
    ],
)
def test_documented_read_only_commands_are_allowed(command):
    decision = validate_command(command)

    assert decision.allowed is True
    assert decision.status == "ok"
    assert decision.matched_pattern


@pytest.mark.parametrize(
    "command",
    [
        # documented verbatim in the ION CLI reference
        "ping 3 8.8.8.8",
        "ping controller1 8.8.8.8",
        "ping controller1 google.com",
        'ping 3 8.8.8.8 args="-c 2"',
        'ping controller1 8.8.8.8 args="-c 10"',
        "tcpping controller1 google.com:80",
        "tcpping 3 10.0.0.1:65535",
        "dig controller1 8.8.8.8 google.com",
    ],
)
def test_documented_diagnostic_commands_are_allowed(command):
    decision = validate_command(command)

    assert decision.allowed is True
    assert decision.matched_pattern in {"ping", "tcpping", "dig"}


@pytest.mark.parametrize(
    "command",
    [
        "show system status",
        "display interfaces",
        "get device status",
        "clear connection",
        "config interface eth0",
        "debug reboot",
        "dump",
        "inspect",
        "dumpx interface status all",
        "dump interface status all; config interface eth0",
        "dump interface status all && config interface eth0",
        "dump interface status all | grep status | config interface eth0",
        "dump interface status all\nconfig interface eth0",
        # allowing bare `ping`/`dig`/`tcpping` must not open the debug family
        # they are documented alongside
        "debug shutdown",
        "debug controller reachability 2",
        "debug bounce interface 3",
        "file remove /tmp/x",
        "curl http://example.com",
        "ssh interface 3",
        "tcpdump 3",
        "traceroute 3 8.8.8.8",
        # arity: each diagnostic is one exact form, not a family
        "ping",
        "ping 3",
        "ping 3 8.8.8.8 extra",
        "dig controller1 8.8.8.8",
        "dig controller1 8.8.8.8 google.com extra",
        "tcpping controller1 google.com",
        "tcpping controller1 google.com:80 extra",
        # bounded ping count, and only -c
        'ping 3 8.8.8.8 args="-c 0"',
        'ping 3 8.8.8.8 args="-c 11"',
        'ping 3 8.8.8.8 args="-c 100"',
        'ping 3 8.8.8.8 args="-s 1400"',
        'ping 3 8.8.8.8 args="-c 3 -s 1400"',
        'ping 3 8.8.8.8 args="-c 3; config interface eth0"',
        "ping 3 8.8.8.8 -c 3",
        # port range
        "tcpping controller1 google.com:0",
        "tcpping controller1 google.com:65536",
        "tcpping controller1 google.com:99999",
        # injection through a diagnostic argument
        "ping 3 8.8.8.8; debug reboot",
        "ping 3 $(debug reboot)",
        "dig controller1 8.8.8.8 google.com && debug shutdown",
        "tcpping controller1 google.com:80 | debug reboot",
    ],
)
def test_non_read_only_or_unknown_commands_are_denied(command):
    decision = validate_command(command)

    assert decision.allowed is False
    assert decision.status == "denied"
    assert decision.reason


def test_mixed_batch_is_rejected_before_execution():
    decision = validate_batch(["dump interface status all", "config interface eth0"])

    assert decision.allowed is False
    assert len(decision.decisions) == 2
    assert decision.decisions[0].allowed is True
    assert decision.decisions[1].allowed is False
    assert "batch rejected" in decision.reason


def test_empty_and_invalid_batches_fail_closed():
    assert validate_batch([]).allowed is False
    assert validate_batch("dump interface status all").allowed is False
    assert validate_command("  dump interface status all").allowed is False


def test_dump_vpn_ka_accepts_a_real_vpn_id_not_just_the_literal_placeholder():
    decision = validate_command("dump vpn ka 1684490871652002728")

    assert decision.allowed is True
    assert decision.matched_pattern == "dump"


@pytest.mark.parametrize(
    "command",
    [
        "debug reboot",
        "debug shutdown",
        "debug controller reachability 2",
        "config interface eth0",
        "clear connection",
        "file remove /tmp/x",
        "curl http://example.com",
        "ssh interface 3",
        "tcpdump 3",
        "traceroute 3 8.8.8.8",
        "dump",
        "inspect",
        "dump interface status all; config interface eth0",
        "dump interface status all & config interface eth0",
        "dump interface status all`config interface eth0`",
        "dump interface status all $(config interface eth0)",
        "dump interface status all > /tmp/x",
        "dump interface status all < /tmp/x",
        "dump interface status all | grep foo | grep bar",
    ],
)
def test_disruptive_and_unmatched_commands_are_refused_by_failing_to_match(command):
    """Explicit refusal set (task 2.4): each is denied because it fails to
    match an approved form, never because it appears on a deny list -- there
    is no deny list in this policy."""
    decision = validate_command(command)

    assert decision.allowed is False


def test_batch_larger_than_the_configured_max_is_rejected_before_evaluation():
    commands = ["dump interface status all"] * 11

    decision = validate_batch(commands, max_commands=10)

    assert decision.allowed is False
    assert decision.decisions == ()
    assert "11" in decision.reason and "10" in decision.reason


def test_batch_at_the_configured_max_is_evaluated_normally():
    commands = ["dump interface status all"] * 10

    decision = validate_batch(commands, max_commands=10)

    assert decision.allowed is True
    assert len(decision.decisions) == 10


def test_policy_resource_is_derived_from_the_validators_own_constants():
    """Published policy cannot drift from real enforcement (task 6.2):
    resources.py imports these constants directly from policy.py rather
    than re-declaring them."""
    import json

    from prisma_sdwan_mcp.cli.policy import ION_DIAGNOSTIC_FORMS, ION_READ_ONLY_FAMILIES
    from prisma_sdwan_mcp.resources import cli_policy_resource

    payload = json.loads(cli_policy_resource())

    assert payload["allowed_families"] == list(ION_READ_ONLY_FAMILIES)
    assert payload["allowed_exact_forms"] == list(ION_DIAGNOSTIC_FORMS)


def test_batch_size_limit_defaults_to_the_config_accessor(monkeypatch):
    from prisma_sdwan_mcp.cli import policy as policy_module

    monkeypatch.setattr(policy_module, "get_ion_max_commands", lambda: 2)

    decision = validate_batch(["dump a", "dump b", "dump c"])

    assert decision.allowed is False
    assert decision.decisions == ()
