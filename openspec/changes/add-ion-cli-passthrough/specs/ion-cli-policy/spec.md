## ADDED Requirements

### Requirement: Deny by default

The system SHALL refuse every ION CLI command that does not match an explicitly approved form, so that safety never depends on an enumeration of dangerous commands staying complete.

There SHALL be no deny list. A command is permitted only by matching an approved family pattern or an approved exact form; anything unmatched is refused with a structured reason.

#### Scenario: Unknown command root is refused

- **WHEN** a command whose root is not `dump`, `inspect`, `ping`, `tcpping`, or `dig` is submitted
- **THEN** the command is refused
- **AND** the reason names the approved families and the approved exact forms

#### Scenario: Disruptive commands stay refused without being listed

- **WHEN** any of `debug reboot`, `debug shutdown`, `debug controller reachability`, `config`, `clear`, `file remove`, `curl`, `ssh`, `tcpdump`, or `traceroute` is submitted
- **THEN** each is refused
- **AND** the refusal comes from failing to match an approved form, not from appearing on a deny list

#### Scenario: A new vendor command is refused until approved

- **WHEN** a command root that did not exist when the policy was written is submitted
- **THEN** it is refused
- **AND** no code change was required to refuse it

### Requirement: Display families are matched at the family level

The system SHALL permit the `dump` and `inspect` families by root plus arguments, rather than by an enumerated list of subcommands, because the vendor reference classifies these commands as display-only at the family level.

A family match SHALL require the root plus at least one trailing argument token; a bare root SHALL be refused.

#### Scenario: Documented display subcommands are permitted

- **WHEN** `dump interface status all` or `inspect wanpaths all` is submitted
- **THEN** each is permitted
- **AND** the decision records which family matched

#### Scenario: An undocumented display subcommand is permitted by family

- **WHEN** a `dump` or `inspect` subcommand not known at implementation time is submitted with safe arguments
- **THEN** it is permitted by the family pattern
- **AND** no policy code change was required

#### Scenario: A bare family root is refused

- **WHEN** `dump` or `inspect` is submitted with no trailing argument
- **THEN** the command is refused

### Requirement: Active diagnostics are matched as exact forms

The system SHALL permit `ping`, `tcpping`, and `dig` only as three exact whole-command shapes, never as families, because these commands send real packets from the device and are documented alongside disruptive `debug` commands.

The permitted shapes are `ping <interface> <host>` with an optional `args="-c N"` where N is 1-10, `tcpping <interface> <host>:<port>` with the port in 1-65535, and `dig <interface> <dns-server> <hostname>`.

#### Scenario: Each documented diagnostic form is permitted

- **WHEN** `ping lan1 10.0.0.1`, `ping lan1 10.0.0.1 args="-c 3"`, `tcpping lan1 10.0.0.1:443`, or `dig lan1 8.8.8.8 example.com` is submitted
- **THEN** each is permitted

#### Scenario: Ping count outside the bound is refused

- **WHEN** `ping lan1 10.0.0.1 args="-c 500"` or a `ping` carrying any flag other than `-c` is submitted
- **THEN** the command is refused

#### Scenario: Out-of-range port is refused

- **WHEN** `tcpping lan1 10.0.0.1:70000` is submitted
- **THEN** the command is refused with a reason naming the valid port range

#### Scenario: A diagnostic root with a different shape is refused

- **WHEN** a `ping`, `tcpping`, or `dig` command with extra, missing, or reordered tokens is submitted
- **THEN** it is refused
- **AND** permitting these three roots does not permit any other command sharing a root or prefix

### Requirement: One output filter, no command chaining

The system SHALL permit at most one `| grep PATTERN` filter after a display-family command, with only the `-i`, `-v`, `-w`, and `-F` options, and SHALL refuse any construct that could turn a permitted prefix into a different command.

Argument tokens SHALL be restricted to a character class that excludes newlines, semicolons, ampersands, backticks, dollar expansion, redirection, and any additional pipe.

#### Scenario: A single grep filter is permitted

- **WHEN** `dump interface status all | grep -i down` is submitted
- **THEN** the command is permitted

#### Scenario: Shell metacharacters are refused

- **WHEN** a command contains `;`, `&`, `` ` ``, `$(`, `>`, `<`, or a second `|`
- **THEN** the command is refused
- **AND** the refusal holds regardless of which permitted root the command starts with

#### Scenario: Control characters are refused

- **WHEN** a command contains a newline, a control character, or leading/trailing whitespace
- **THEN** the command is refused

### Requirement: A batch is validated before any connection

The system SHALL evaluate every command in a batch against the policy before opening a network connection, and SHALL reject the entire batch if any single command is refused.

A rejected batch SHALL return one structured decision per submitted command, each carrying its individual reason, and SHALL NOT contact the device.

#### Scenario: One refused command rejects the batch

- **WHEN** a batch containing two permitted commands and one refused command is submitted
- **THEN** the whole batch is rejected
- **AND** the response contains one decision entry per submitted command including the two that would have been permitted

#### Scenario: A rejected batch opens no connection

- **WHEN** a batch is rejected by the policy
- **THEN** no SSH connection is attempted
- **AND** no credential is read or transmitted

#### Scenario: An empty or malformed batch is rejected

- **WHEN** the command list is empty, is not a list, or contains a non-string entry
- **THEN** the batch is rejected with a reason describing the input problem

### Requirement: The enforced policy is browsable

The system SHALL expose the policy it actually enforces as a readable resource generated from the same constants the validator uses, so published policy cannot drift from real enforcement.

#### Scenario: Policy resource reflects enforcement

- **WHEN** the policy resource is read
- **THEN** it lists the approved families, the approved exact diagnostic forms, and the supported output filter
- **AND** those values are derived from the same definitions the validator evaluates
- **AND** no denied commands are listed, because refusal is the default rather than an enumeration
