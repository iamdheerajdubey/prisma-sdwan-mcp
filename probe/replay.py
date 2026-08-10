#!/usr/bin/env python3
"""
Offline replay: run captured ION bytes through the real code path, no device.

    python probe/replay.py

Why this exists
---------------
Five live runs were spent finding bugs one layer at a time, because each fix
needed another trip to the lab to evaluate. That was avoidable from run 3
onwards: probe/results/*/raw/direct_*.txt already held the device's exact
bytes, and everything downstream of the socket is deterministic given those
bytes.

The bug that made it worst is a race. `dump overview` returned 1627 bytes in
one run and 82 -- the command echo alone -- in the next, from identical code.
The device echoes 'PROMPT# command' before any data, so a prompt-based read
terminator can match the echo and stop, and whether it does depends on whether
the real output happened to arrive in the same channel read. Observing that
once per round trip is the slowest possible way to fix it.

This replays the worst case deterministically: the echo arrives alone, the
output follows. If the completion pattern is wrong, every command truncates
here, every time.

Data source
-----------
Reads the newest probe/results/*/raw/direct_*.txt. Those are verbatim device
captures including ANSI escapes. The trailing prompt netmiko strips before
saving is re-appended, because it is what the read is supposed to stop on.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from prisma_sdwan_mcp.cli.ssh import (  # noqa: E402
    _command_result,
    _completion_pattern,
    _normalise_prompt,
)

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RAW_PROMPT = "\x1b[31mAEDXB01-SDE01#\x1b[0m  \x08"
PROMPT_TEXT = "AEDXB01-SDE01#"

FAILURES: list[str] = []


def newest_capture_dir() -> Path:
    runs = sorted((REPO / "probe" / "results").glob("*/raw"))
    if not runs:
        sys.exit("no probe/results/*/raw found - run the probe once first")
    for candidate in reversed(runs):
        if list(candidate.glob("direct_*.txt")):
            return candidate
    sys.exit("no direct_*.txt captures found in any run")


class ReplayConnection:
    """A netmiko session that hands back one captured transcript.

    Faithful to the failure that matters: `send_command` reads the channel
    until `expect_string` matches and returns everything up to that point. A
    pattern that matches inside the echo therefore returns the echo, exactly
    as the device made it do.
    """

    def __init__(self, transcript: str, strip_ansi: bool = True):
        # The server sets ansi_escape_codes=True, so netmiko strips these
        # before our code ever sees them. Replay that.
        self.transcript = ANSI.sub("", transcript) if strip_ansi else transcript
        self.prompt = ANSI.sub("", RAW_PROMPT) if strip_ansi else RAW_PROMPT

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


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))
    if not condition:
        FAILURES.append(f"{name}: {detail}")


def main() -> int:
    raw_dir = newest_capture_dir()
    print(f"replaying captures from {raw_dir.relative_to(REPO)}\n")

    prompt = _normalise_prompt(RAW_PROMPT)
    pattern = _completion_pattern(ReplayConnection(""))
    print(f"prompt      : {prompt!r}")
    print(f"completion  : {pattern!r}\n")

    # --- the pattern itself, against the shapes the device actually emits ---
    print("completion pattern:")
    compiled = re.compile(pattern)
    check("does not match the command echo",
          not compiled.search(f"{PROMPT_TEXT} dump interface status all"))
    check("does not match a second echo line",
          not compiled.search(f"{PROMPT_TEXT} dump overview\n{PROMPT_TEXT} dump overview"))
    check("matches an idle prompt", bool(compiled.search(PROMPT_TEXT)))
    check("matches an idle prompt with trailing control bytes",
          bool(compiled.search(f"{PROMPT_TEXT}  \x08")))
    check("matches a pager", bool(compiled.search("data\n--More--")))

    # --- every captured command, through the real result builder ------------
    print("\ncaptured commands through _command_result:")
    for capture in sorted(raw_dir.glob("direct_*.txt")):
        label = capture.stem.replace("direct_", "")
        device_output = capture.read_text(encoding="utf-8")
        # Re-append the trailing prompt: netmiko strips it before the probe
        # writes the file, but it is what the read is meant to terminate on.
        transcript = device_output.rstrip("\n") + f"\n{RAW_PROMPT}"
        connection = ReplayConnection(transcript)

        result = _command_result(
            connection, f"dump {label}", read_timeout=30.0, max_output_bytes=40960,
            secrets=("hunter2",),
        )
        body = result.get("output") or result.get("error") or ""
        expected = ANSI.sub("", device_output).rstrip("\n")
        complete = body.rstrip("\n") == expected

        detail = f"{len(body)} of {len(expected)} bytes, status={result.get('status')}"
        check(f"{label}: full output survives", complete, detail)

    # --- error classification, on the real rejection ------------------------
    print("\nerror classification:")
    rejection = (raw_dir / "direct_rejected.txt")
    if rejection.exists():
        transcript = rejection.read_text(encoding="utf-8").rstrip("\n") + f"\n{RAW_PROMPT}"
        result = _command_result(
            ReplayConnection(transcript), "dump zzznosuch",
            read_timeout=30.0, max_output_bytes=40960, secrets=(),
        )
        check("a rejected command is status=error", result.get("status") == "error",
              f"got {result.get('status')}")

    good = (raw_dir / "direct_large.txt")
    if good.exists():
        transcript = good.read_text(encoding="utf-8").rstrip("\n") + f"\n{RAW_PROMPT}"
        result = _command_result(
            ReplayConnection(transcript), "dump interface status all",
            read_timeout=30.0, max_output_bytes=40960, secrets=(),
        )
        check("valid output is status=ok", result.get("status") == "ok",
              f"got {result.get('status')}")

        # --- truncation, which no live run has ever actually exercised ------
        print("\ntruncation:")
        result = _command_result(
            ReplayConnection(transcript), "dump interface status all",
            read_timeout=30.0, max_output_bytes=4096, secrets=(),
        )
        check("fires below the cap", bool(result.get("truncated")),
              f"truncated={result.get('truncated')}")
        check("declares bytes returned and total",
              result.get("output_bytes") is not None
              and result.get("output_bytes_total") is not None,
              f"returned={result.get('output_bytes')} total={result.get('output_bytes_total')}")
        check("returned is under the cap", (result.get("output_bytes") or 0) <= 4096,
              str(result.get("output_bytes")))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("all replay checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
