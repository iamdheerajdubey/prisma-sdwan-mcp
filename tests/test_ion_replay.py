"""
Replay real ION captures through the real code path, in CI, with no device.

The live probe found five bugs across five lab round-trips, and three of those
trips were spent evaluating a fix that could have been checked here in a
second. Everything below the socket is deterministic given the device's bytes,
and probe/results/*/raw/direct_*.txt holds them, so this makes the captures a
permanent regression fixture instead of a one-off observation.

The bug worth pinning is a race: `dump overview` returned 1627 bytes in one run
and 82 -- its own echo -- in the next, from identical code. The device echoes
'PROMPT# command' before any data, so a prompt-based read terminator can match
the echo and stop, depending on whether the real output arrived in the same
channel read. Replay makes the losing case happen every time.
"""

from __future__ import annotations

import pytest

replay = pytest.importorskip("probe.replay", reason="probe package not importable")


@pytest.fixture(scope="module")
def capture_dir():
    try:
        return replay.newest_capture_dir()
    except SystemExit as exc:
        pytest.skip(str(exc))


def test_replay_of_every_captured_command_passes(capture_dir, capsys):
    """One assertion over the whole replay, so a new capture is covered the
    moment it lands without anyone editing this file."""
    exit_code = replay.main()
    output = capsys.readouterr().out

    assert exit_code == 0, f"replay reported failures:\n{output}"


def test_the_completion_pattern_never_matches_an_echo(capture_dir):
    """The single defect behind the race, stated directly."""
    import re

    pattern = re.compile(replay._completion_pattern(replay.ReplayConnection("")))
    prompt = replay.PROMPT_TEXT

    for command in ("dump overview", "dump interface status all", "dump config"):
        assert not pattern.search(f"{prompt} {command}"), (
            f"pattern matches the echo of {command!r}; the read would stop there "
            "and return the echo as the device's answer"
        )
    assert pattern.search(prompt), "an idle prompt must still terminate the read"
