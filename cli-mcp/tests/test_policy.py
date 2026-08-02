import pytest

from prisma_sdwan_cli_mcp.policy import validate_batch, validate_command


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
        # inspect family is trusted per RESEARCH.md, not because this exact
        # subcommand is listed anywhere
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
