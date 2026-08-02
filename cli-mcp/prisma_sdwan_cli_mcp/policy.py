"""Fail-closed read-only policy for the Palo Alto Prisma SD-WAN ION CLI.

Palo Alto's ION CLI reference splits commands into families, not individual
subcommands: `dump` and `inspect` are documented as display-only and
available to read roles; `clear`, `config`, and `debug` are the write/
disruptive families. This policy trusts that documented family boundary
directly instead of enumerating every known `dump`/`inspect` subcommand
(that enumeration drifts out of date and duplicates a classification the
vendor already makes at the family level). See RESEARCH.md.
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

    for family, pattern in ION_READ_ONLY_PATTERNS:
        if pattern.fullmatch(command):
            return CommandDecision(
                command_text,
                True,
                f"matches ION read-only family '{family}'",
                family,
            )

    return CommandDecision(
        command_text,
        False,
        "command is not a recognized ION read-only command "
        f"(must start with one of: {', '.join(ION_READ_ONLY_FAMILIES)})",
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
    return BatchDecision(True, decisions, "all commands matched the ION read-only whitelist")
