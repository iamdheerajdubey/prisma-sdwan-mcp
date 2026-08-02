# ION CLI Research

Research completed 2026-08-02 before implementation. The official Palo Alto Networks ION CLI reference was used because this workspace has no ION/SSH lab configuration or captured CLI session.

## Read-only command surface

The current official reference documents five top-level command families: `clear`, `config`, `debug`, `dump`, and `inspect`.

- `inspect` is described as displaying information about interfaces, devices, and routing, and is available to Super and Read Only roles.
- `dump` is described as displaying information about interfaces, devices, and routing, and is available to all user roles.
- `clear` clears status, `config` configures interfaces/devices/routing, and `debug` includes disruptive operations such as reboot and shutdown. Those three families are denied.
- The official command indexes enumerate 148 documented `dump` forms and 42 documented `inspect` forms — every one of them display-only, none in either family documented as mutating device state. The policy trusts the `dump`/`inspect` family boundary itself (as Palo Alto's own docs draw it) rather than re-enumerating each of those 190 forms as a separate whitelist entry: any `dump`/`inspect` command matching the safe-argument character class is allowed, any `clear`/`config`/`debug`/unknown-root command is denied. An earlier revision of this policy did enumerate exact forms one by one; that approach both drifted out of date (see the `dump vpn ka <VpnID>` example below) and added no security value the family-level split doesn't already provide, so it was replaced.
- `show`, `display`, and `get` are not ION command families in the current reference and are therefore denied by default.

Representative documented forms (all covered by the `dump`/`inspect` family match, none individually enumerated):

- `dump interface status all`
- `dump interface status interface=controller1`
- `inspect system arp all`
- `inspect wanpaths site-id=1684490871652002728`
- `dump vpn ka <VpnID>` — `<VpnID>` is a variable position, not a literal
  token. This is exactly the kind of drift an exact-form whitelist is prone
  to: an earlier revision encoded the doc's `<VpnID>` placeholder as the
  literal required word `VpnID`, silently making that one form unusable.
  Trusting the family instead of the exact form removes this class of bug.

Sources:

- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/use-cli-commands.html
- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/use-cli-commands/dump-commands.html
- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/use-cli-commands/inspect-commands.html
- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/use-cli-commands/dump-commands/dump-interface-status.html
- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/use-cli-commands/inspect-commands/inspect-system-arp.html
- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/use-cli-commands/inspect-commands/inspect-wan-paths.html

## Pipes, chaining, and shell syntax

The official reference documents one output filter form: `COMMAND | grep PATTERN`, with `grep` options `-i`, `-v`, `-w`, and `-F`. The policy permits at most one such grep filter after a documented `dump` or `inspect` command.

No official ION CLI page or local capture available to this implementation documents command chaining, subshell expansion, redirection, or a second pipe. The whitelist therefore rejects semicolons, ampersands, backticks, dollar expansion, angle brackets, newlines, and any additional pipe. The filter pattern is restricted to shell-free printable tokens.

## Pagination and prompts

The official command pages and reference PDF extraction do not document `--More--`, pager configuration, `terminal length`, or another pagination prompt. No lab device was available to verify this behavior. This is an explicit unverified point, not a claim that ION never paginates.

The executor consequently uses Netmiko timing reads and defensively answers recognized `--More--`/`(q)uit`-style prompts with a space, while bounding the number of pages and read time. If a future lab capture shows a different marker or a device-specific prompt, update the marker table and tests.

## Authentication

The official SSH access page says to connect with `ssh username@<ip address>` and enter a password. v1 supports that documented password flow and also accepts inline private-key material per the change contract (`password` or `private_key`, exactly one). Key material is passed only for the current Netmiko connection; key files and local inventories are not read. Whether a specific ION deployment permits public-key authentication remains a device/security-policy question and should be validated in the target lab.

Independent of credential material, the connection itself uses strict SSH host-key checking (`ssh_strict=True`, `system_host_keys=True`) rather than trusting whatever host key the far end presents. The documented `ssh username@<ip address>` flow already implies a host-key prompt/acceptance on first connect in any normal SSH client; this server requires that acceptance to already be recorded in known_hosts (or an alternate file passed as `known_hosts_file`) rather than performing it silently, so credentials are never sent to an unverified host.

Source:

- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/access-the-ion-cli-commands/access-through-ssh.html
