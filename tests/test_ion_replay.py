"""
Replay real ION captures through the real code path, in CI, with no device.

`tests/fixtures/ion/` holds bytes captured verbatim from a live ION 1200
running 6.3.6-b9, including the ANSI escapes and the doubled command echo the
device really emits. Everything below the socket is deterministic given those
bytes, so the behaviour that used to need a lab round trip to check is settled
here in milliseconds.

The bug worth pinning is a race. `dump overview` returned 1627 bytes in one
live run and 82 -- its own echo -- in the next, from identical code, with
status "ok" both times. The device echoes 'PROMPT# command' before any data, so
a prompt-based read terminator can match the echo and stop, depending on
whether the real output arrived in the same channel read. Replaying a fixed
transcript makes the losing case happen every time, so the failure is
reproducible instead of intermittent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from prisma_sdwan_mcp.cli.ssh import (
    _command_result,
    _completion_pattern,
    _normalise_prompt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ion"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Captured from the live device: a coloured prompt with trailing spaces and a
# backspace. str.strip() does not remove the backspace, which is what made an
# earlier fix silently never fire.
RAW_PROMPT = "\x1b[31mAEDXB01-SDE01#\x1b[0m  \x08"
PROMPT_TEXT = "AEDXB01-SDE01#"


class ReplayConnection:
    """A netmiko session that hands back one captured transcript.

    Faithful to the failure that matters: ``send_command`` reads until
    ``expect_string`` matches and returns everything up to that point. A
    pattern that matches inside the echo therefore returns the echo, exactly as
    the device made it do.
    """

    def __init__(self, transcript: str):
        # The server sets ansi_escape_codes=True, so netmiko strips these
        # before our code sees them. Replay that.
        self.transcript = ANSI.sub("", transcript)
        self.prompt = ANSI.sub("", RAW_PROMPT)

    def find_prompt(self) -> str:
        return self.prompt

    def send_command(self, command, expect_string=None, read_timeout=None,
                     strip_prompt=True, strip_command=True, **_kwargs) -> str:
        body = self.transcript
        if expect_string:
            match = re.search(expect_string, body)
            body = body[: match.start()] if match else body
        return body

    def read_until_pattern(self, pattern=None, read_timeout=None) -> str:
        return ""

    def write_channel(self, data: str) -> None:
        return None


def _transcript(name: str) -> str:
    """Captured output plus the trailing prompt netmiko strips before saving.

    The prompt is re-appended because it is what the read is supposed to stop
    on -- without it the fixture cannot exercise termination at all.
    """
    raw = (FIXTURES / f"direct_{name}.txt").read_text(encoding="utf-8")
    return raw.rstrip("\n") + f"\n{RAW_PROMPT}"


def _result(name: str, command: str, max_output_bytes: int = 40960) -> dict:
    return _command_result(
        ReplayConnection(_transcript(name)), command,
        read_timeout=30.0, max_output_bytes=max_output_bytes, secrets=(),
    )


CAPTURES = sorted(p.stem.replace("direct_", "") for p in FIXTURES.glob("direct_*.txt"))


def test_fixtures_are_present():
    assert CAPTURES, "tests/fixtures/ion/direct_*.txt is missing"
    assert "large" in CAPTURES and "rejected" in CAPTURES


# ---------------------------------------------------------------------------
# The completion pattern, against the shapes the device actually emits
# ---------------------------------------------------------------------------
def test_the_pattern_never_matches_a_command_echo():
    pattern = re.compile(_completion_pattern(ReplayConnection("")))

    for command in ("dump overview", "dump interface status all", "dump config"):
        assert not pattern.search(f"{PROMPT_TEXT} {command}"), (
            f"pattern matches the echo of {command!r}; the read would stop there "
            "and return the echo as the device's answer"
        )


def test_the_pattern_matches_an_idle_prompt_and_a_pager():
    pattern = re.compile(_completion_pattern(ReplayConnection("")))

    assert pattern.search(PROMPT_TEXT)
    assert pattern.search(f"{PROMPT_TEXT}  \x08"), "trailing control bytes are real"
    assert pattern.search("Interface: lan1\nAEDXB01-SDE01# ")
    assert pattern.search("data\n--More--")


def test_prompt_normalisation_strips_trailing_control_bytes():
    """netmiko strips the ANSI escapes before find_prompt() returns, so what
    reaches _normalise_prompt is the colour codes' text residue plus the
    trailing spaces and backspace. The backspace is the point: it is not
    whitespace, so str.strip() leaves it, and an earlier fix that compared
    `prompt in line` therefore never matched anything."""
    seen_in_production = ANSI.sub("", RAW_PROMPT)

    assert seen_in_production == f"{PROMPT_TEXT}  \x08"
    assert _normalise_prompt(seen_in_production) == PROMPT_TEXT
    assert _normalise_prompt("") is None
    assert _normalise_prompt(None) is None


# ---------------------------------------------------------------------------
# Every captured command, through the real result builder
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", CAPTURES)
def test_full_output_survives(name):
    """The regression: output must not be cut short at its own echo."""
    expected = ANSI.sub("", (FIXTURES / f"direct_{name}.txt").read_text(encoding="utf-8"))
    result = _result(name, f"dump {name}")
    body = (result.get("output") or result.get("error") or "").rstrip("\n")

    assert body == expected.rstrip("\n"), (
        f"{name}: got {len(body)} of {len(expected.rstrip(chr(10)))} bytes"
    )


# ---------------------------------------------------------------------------
# Error classification, on the device's real wording
# ---------------------------------------------------------------------------
def test_a_real_rejection_is_status_error():
    """The ION echoes prompt and command twice before 'unknown keyword'."""
    assert _result("rejected", "dump zzznosuch")["status"] == "error"


def test_valid_output_is_status_ok():
    assert _result("large", "dump interface status all")["status"] == "ok"


# ---------------------------------------------------------------------------
# Truncation -- no live run ever reached this, 11 KB never hitting a 40 KB cap
# ---------------------------------------------------------------------------
def test_truncation_fires_and_declares_both_byte_counts():
    result = _result("large", "dump interface status all", max_output_bytes=4096)

    assert result["truncated"] is True
    assert result["output_bytes"] <= 4096
    assert result["output_bytes_total"] > result["output_bytes"]


def test_output_within_the_cap_is_not_marked_truncated():
    assert _result("small", "dump overview")["truncated"] is False
