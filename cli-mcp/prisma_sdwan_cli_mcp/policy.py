"""Fail-closed policy for the Palo Alto Prisma SD-WAN ION CLI.

Palo Alto's ION CLI reference splits commands into families, not individual
subcommands: `dump` and `inspect` are documented as display-only and
available to read roles; `clear`, `config`, and `debug` are the write/
disruptive families. This policy trusts that documented family boundary
directly instead of enumerating every known `dump`/`inspect` subcommand
(that enumeration drifts out of date and duplicates a classification the
vendor already makes at the family level). See RESEARCH.md.

A second, much narrower group is allowed on top of that: the active
diagnostics `ping`, `tcpping`, and `dig`. These are *not* family matches --
each is one exact documented form, matched whole. They are documented on
the reference's Debug Commands pages but are typed as bare roots with no
`debug` prefix, so allowing them does not open the `debug` family: `debug
reboot`, `debug shutdown`, `file remove`, `curl`, and `ssh` all remain
unmatched and therefore denied.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


_SAFE_ARGUMENT = r"[A-Za-z0-9][A-Za-z0-9_.:/=-]*"
_GREP_ARGUMENT = r"[A-Za-z0-9][A-Za-z0-9_.:/=,*?+\-\[\]{}^]*"
_GREP_FILTER = rf"(?:\s+\|\s+grep(?:\s+-(?:i|v|w|F))*\s+{_GREP_ARGUMENT}(?:\s+{_GREP_ARGUMENT})*)?"

# Documented read-only ION CLI command families. Everything else (including
# unknown roots) is denied by default.
ION_READ_ONLY_FAMILIES = ("dump", "inspect")

ION_READ_ONLY_PATTERNS = tuple(
    (
        family,
        re.compile(rf"^{re.escape(family)}(?:\s+{_SAFE_ARGUMENT})+{_GREP_FILTER}$"),
    )
    for family in ION_READ_ONLY_FAMILIES
)

# Range-checked after the match rather than in the pattern: a regex spelling
# of 1-65535 is unreadable and easy to get subtly wrong.
_PORT = r"(?P<port>[0-9]{1,5})"
# ION's own default is 5 packets and the command terminates on its own, so
# `args` is optional. Only `-c` is accepted, bounded, and nothing the caller
# supplies is ever placed inside the quotes -- they are literals here.
_PING_COUNT = r"(?:[1-9]|10)"

# Exact documented forms, not families. Each is matched whole.
ION_DIAGNOSTIC_PATTERNS = (
    (
        "ping",
        re.compile(
            rf'^ping {_SAFE_ARGUMENT} {_SAFE_ARGUMENT}'
            rf'(?: args="-c {_PING_COUNT}")?$'
        ),
    ),
    ("tcpping", re.compile(rf"^tcpping {_SAFE_ARGUMENT} {_SAFE_ARGUMENT}:{_PORT}$")),
    ("dig", re.compile(rf"^dig {_SAFE_ARGUMENT} {_SAFE_ARGUMENT} {_SAFE_ARGUMENT}$")),
)

ION_DIAGNOSTIC_FORMS = (
    'ping <interface> <host> [args="-c 1..10"]',
    "tcpping <interface> <host>:<port>",
    "dig <interface> <dns-server> <hostname>",
)

ION_COMMAND_PATTERNS = ION_READ_ONLY_PATTERNS + ION_DIAGNOSTIC_PATTERNS


@dataclass(frozen=True)
class CommandDecision:
    command: str
    allowed: bool
    reason: str
    matched_pattern: str | None = None

    @property
    def status(self) -> str:
        return "ok" if self.allowed else "denied"

    def __iter__(self):
        yield self.allowed
        yield self.reason


@dataclass(frozen=True)
class BatchDecision:
    allowed: bool
    decisions: tuple[CommandDecision, ...]
    reason: str


def _command_text(command: object) -> str:
    return command if isinstance(command, str) else str(command)


def validate_command(command: object) -> CommandDecision:
    command_text = _command_text(command)
    if not isinstance(command, str):
        return CommandDecision(command_text, False, "command must be a string")
    if not command:
        return CommandDecision(command_text, False, "command must not be empty")
    if command != command.strip():
        return CommandDecision(
            command_text,
            False,
            "leading or trailing whitespace is not allowed",
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in command):
        return CommandDecision(
            command_text,
            False,
            "control characters and newlines are not allowed",
        )

    for family, pattern in ION_COMMAND_PATTERNS:
        match = pattern.fullmatch(command)
        if match is None:
            continue
        port = match.groupdict().get("port")
        if port is not None and not 1 <= int(port) <= 65535:
            return CommandDecision(
                command_text,
                False,
                "port must be between 1 and 65535",
            )
        return CommandDecision(
            command_text,
            True,
            f"matches approved ION command form '{family}'",
            family,
        )

    return CommandDecision(
        command_text,
        False,
        "command does not match any approved ION command form "
        f"(families: {', '.join(ION_READ_ONLY_FAMILIES)}; "
        f"exact forms: {'; '.join(ION_DIAGNOSTIC_FORMS)})",
    )


def validate_batch(commands: Iterable[object]) -> BatchDecision:
    if not isinstance(commands, (list, tuple)):
        return BatchDecision(False, (), "commands must be a list of strings")

    decisions = tuple(validate_command(command) for command in commands)
    if not decisions:
        return BatchDecision(False, (), "commands must contain at least one command")
    if any(not decision.allowed for decision in decisions):
        return BatchDecision(
            False,
            decisions,
            "batch rejected because one or more commands failed the read-only policy",
        )
    return BatchDecision(True, decisions, "all commands matched an approved ION command form")
