# Diagnostic probe

Drives this MCP server against a real ION and records what happens, in enough
detail to fix what it finds after the device is gone.

Written to be run by an agent with no human in the loop, and read by an agent
that was not present when it ran.

## Running it

On the Linux server that can reach an ION:

```bash
git clone git@github.com:iamdheerajdubey/prisma-sdwan-mcpv2.git ~/prisma-mcp
cd ~/prisma-mcp   # not /tmp: it is often mounted noexec, which breaks the venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .

cp .env.example .env      # then fill in the three lines below
.venv/bin/python probe/run_probe.py
```

All `.env` needs is what you would type to SSH in by hand:

```
ION_IP=10.0.0.1
ION_USERNAME=admin
ION_PASSWORD=...
```

Optionally `ION_ELEMENT=<name>` plus the `PAN_*` credentials, to also exercise
controller-backed name resolution. Everything else has a working default.

The host key is handled for you. The server has no first-use trust, so an
unknown device is normally refused — but demanding a manual `ssh-keyscan`
before the probe can do anything is pure friction, and `ssh-keyscan` returns
nothing at all on devices that only offer `ssh-rsa`. The probe fetches the key
itself and writes a `known_hosts` into its own results directory. Trust is not
skipped, it is *recorded*: the fingerprint lands in `findings.json`, so what
the run trusted stays auditable even though nobody verified it at the time.
Set `PRISMA_ION_KNOWN_HOSTS` explicitly and the probe leaves it alone.

Then commit `probe/results/<run id>/` and push. That directory is the entire
deliverable.

> **Read before running.** The probe captures **full raw device output** on
> purpose — it is the only way to answer G1. Anything your ION prints,
> including secrets in its configuration, lands in `probe/results/` and
> therefore in git history. Point it at a device you are willing to expose and
> treat the resulting repository as sensitive.

Everything it sends is a command the policy already permits. Nothing is
configured, cleared or restarted on the device.

## What it is looking for

| Gap | Question | How it is answered |
|---|---|---|
| **G1** | Can secret redaction reach CLI text at all? | Runs `dump overview` and `dump interface status all`, scans the raw output for candidate secrets, then runs the real `ResponseSafety.redact()` over the real response and records whether it changed anything. Secrets present + nothing changed = the gap is real. |
| **G2** | Is `run_commands` exposed without authentication over HTTP? | Starts the server on `127.0.0.1:<ephemeral>`, connects as an MCP client with no credentials, lists tools, and calls `run_commands` against the ION. Loopback only — never reachable from the network. |
| **G3** | Does the device put its error on the first line? | Sends a command the policy permits and the device rejects, then captures the exact bytes with `repr()` so whitespace and caret markers are visible, and checks whether `_is_device_error()` fired. The same first-line assumption was already proven wrong on Cisco IOS. |
| **G4** | Does a caller receive enough to tell truncated output from whole output? | Captures the result fields and byte counts for the large command. |
| **G5** | Does controller-backed name resolution work? | Only if `ION_ELEMENT` is set; otherwise recorded as `not_run`. |

## Reading the results

```
probe/results/<UTC timestamp>/
  findings.json     <- start here: every check, its status, and its evidence
  environment.json  <- platform, versions, which credentials were present
  console.log       <- everything printed, in order
  raw/
    small_output.txt                  dump overview, verbatim
    large_output.txt                  dump interface status all, verbatim
    rejected_output.txt               what the device said to a bad command
    *_response.json                   the tool's full response envelope
    *_after_safety_redact.json        the same, after the real redactor ran
    http_server_std{out,err}.txt      the HTTP server's own logs
```

Each finding carries one of five statuses. They mean different things and must
not be collapsed:

- **proven** — the gap is real, and the evidence is in the same record.
- **disproven** — the gap does not exist on this device, for this command.
- **inconclusive** — the check ran but the result settles nothing. The verdict
  field says what would settle it.
- **not_run** — a precondition was missing. **This is not evidence of absence.**
- **crashed** — the probe itself failed. The traceback is attached; the gap is
  unresolved, not absent.

A run where everything says `not_run` is a failed run, not a clean bill of
health.

## Design rules

- **Detectors are isolated.** One crashing does not cost the others their
  results, because a partial run still narrows the problem.
- **Nothing is inferred.** A check that could not run says so and says why.
- **The current working directory never matters.** `.env` is loaded by explicit
  path, results are written relative to this file. Run it from `/tmp`, from the
  repo, from `/`.
- **Linux and Windows behave the same.** No shell invocations, no hard-coded
  separators, `~` expanded through `os.path.expanduser`, all files written with
  explicit UTF-8 and `\n`.
