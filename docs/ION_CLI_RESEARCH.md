# ION CLI Research

Research completed 2026-08-02 before implementation. The official Palo Alto Networks ION CLI reference was used because this workspace has no ION/SSH lab configuration or captured CLI session.

## Read-only command surface

The current official reference groups commands into five documented sections: `clear`, `config`, `debug`, `dump`, and `inspect`. Note that these are *documentation sections*, not typed command roots — the Debug Commands section documents several commands that are typed as bare roots with no `debug` prefix (`ping`, `ping6`, `tcpping`, `dig`, `traceroute`, `tcpdump`, `curl`, `arping`, `ssh`, `file ...`) alongside the ones that do carry it (`debug reboot`, `debug shutdown`, `debug bounce interface`, `debug controller reachability`, …). An earlier revision of this file described the five as "top-level command families", which made the diagnostics below look like they did not exist in the reference at all.

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

## Active diagnostics

Three commands from the Debug Commands section are allowed on top of the `dump`/`inspect` families. Unlike those families, each is one **exact documented form matched whole** — there is no `ping` family, only these shapes:

```text
ping <interface> <host> [args="-c 1..10"]
tcpping <interface> <host>:<port>
dig <interface> <dns-server> <hostname>
```

Verified against the reference and against a live I390 ION session:

```text
I390ION1# ping 3 8.8.8.8
PING 8.8.8.8 (8.8.8.8) from 156.70.134.86: 56 data bytes
64 bytes from 8.8.8.8: seq=0 ttl=116 time=2.528 ms
...
5 packets transmitted, 5 packets received, 0% packet loss
I390ION1# ping 3 8.8.8.8 args="-c 2"
```

Notes:

- Bare `ping` terminates on its own at 5 packets — ION's default, confirmed on device. There is no infinite-ping risk in the bare form, so `args` is optional.
- The reference documents a wider `args` set (`-s`, `-W`, `-w`, `-i`, `-I`, `-t`, `-q`, `-p`). Only `-c` is permitted, bounded 1-10. The quote characters appear as literals inside the compiled pattern; nothing caller-supplied is ever placed inside them, so this does not introduce general quoted-string handling.
- The `interface` position accepts an interface name (`controller1`) or a numeric interface ID (`3`) — both appear in the official examples.
- `tcpping`'s parameter is documented as `dst-ipv4:port` but the official example uses a hostname (`tcpping controller1 google.com:80`), so hostnames are accepted. Port is range-checked 1-65535 after the match.
- Allowing these bare roots does **not** open the `debug` family. `debug reboot`, `debug shutdown`, `debug controller reachability`, `file remove`, `curl`, `ssh`, `tcpdump`, and `traceroute` are all unmatched and therefore denied, and there are tests asserting exactly that.
- `debug controller reachability <interface>` is real and documented (`debug controller reachability 2`) but is **deliberately deferred**: it is a carve-out inside the family that also holds `reboot` and `shutdown`, and the API MCP already reports controller connectivity.
- These commands send real packets. `run_commands` therefore no longer advertises `readOnlyHint`/`idempotentHint`.
- Role: the Debug Commands page states only SUPER users may execute debug commands, while the `dig` page lists Super, Read Only, and Monitor. The MCP does not model roles — it passes whatever credential the caller supplies and surfaces the device's own rejection (`_is_device_error` matches a leading `permission denied`). Privilege is the operator's concern, not the server's.

## Pipes, chaining, and shell syntax

The official reference documents one output filter form: `COMMAND | grep PATTERN`, with `grep` options `-i`, `-v`, `-w`, and `-F`. The policy permits at most one such grep filter after a documented `dump` or `inspect` command.

No official ION CLI page or local capture available to this implementation documents command chaining, subshell expansion, redirection, or a second pipe. The whitelist therefore rejects semicolons, ampersands, backticks, dollar expansion, angle brackets, newlines, and any additional pipe. The filter pattern is restricted to shell-free printable tokens.

## Pagination and prompts

The official command pages and reference PDF extraction do not document `--More--`, pager configuration, `terminal length`, or another pagination prompt. No lab device was available to verify this behavior. This is an explicit unverified point, not a claim that ION never paginates.

The executor defensively answers recognized `--More--`/`(q)uit`-style prompts with a space, while bounding the number of pages. If a future lab capture shows a different marker, update the marker table and tests.

## Completion detection

Command completion is decided by the **device prompt reappearing**, not by the channel falling quiet. The prompt is discovered per-session with `find_prompt()` (it is the device hostname plus `#`, e.g. `I390ION1#`, so it cannot be hardcoded).

An earlier revision used `send_command_timing(last_read=0.3)`, which treats 0.3s of silence as "command finished". That is correct for `dump`/`inspect`, which answer instantly, and **silently wrong** for `ping`, which emits roughly one line per second: the reader returned after the first packet and reported `status: ok`. Raising the silence threshold only moves the guess; keying off the prompt removes it. Command duration is now irrelevant to the MCP — a command runs as long as it runs.

`DEFAULT_READ_TIMEOUT` (300s) remains only as a hang ceiling for a session that has stopped responding entirely and will never return a prompt. Most MCP clients give the caller no way to cancel an in-flight tool call, so some ceiling has to exist. Hitting it produces `status: error`, never a truncated success.

## Authentication

The official SSH access page says to connect with `ssh username@<ip address>` and enter a password. v1 supports that documented password flow and also accepts inline private-key material per the change contract (`password` or `private_key`, exactly one). Key material is passed only for the current Netmiko connection; key files and local inventories are not read. Whether a specific ION deployment permits public-key authentication remains a device/security-policy question and should be validated in the target lab.

Independent of credential material, the connection itself uses strict SSH host-key checking (`ssh_strict=True`, `system_host_keys=True`) rather than trusting whatever host key the far end presents. The documented `ssh username@<ip address>` flow already implies a host-key prompt/acceptance on first connect in any normal SSH client; this server requires that acceptance to already be recorded in known_hosts (or an alternate file passed as `known_hosts_file`) rather than performing it silently, so credentials are never sent to an unverified host.

Source:

- https://docs.paloaltonetworks.com/prisma-sd-wan/ion-cli-reference/access-the-ion-cli-commands/access-through-ssh.html
