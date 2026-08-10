#!/usr/bin/env python3
"""
Diagnostic probe — drives this MCP server against a real ION and records what
happens, in enough detail to fix what it finds without the device present.

    python probe/run_probe.py

No arguments. Reads .env from the repository root. Writes everything to
probe/results/<UTC timestamp>/ for committing and review.

WHAT IT IS FOR
--------------
Three suspected gaps cannot be settled by unit tests, because each one is a
disagreement between what the code assumes and what a real device does:

  G1  Secret redaction is key-based (safety.py walks dict keys). CLI output is
      one text blob under a non-sensitive key, so redaction may be structurally
      incapable of touching it. Proven or disproven by running both the real
      redactor and a candidate text scanner over genuine ION output.

  G2  There is no registration gate and no transport gate. Started over HTTP,
      the server may expose an SSH-to-ION proxy with stored credentials to any
      caller, with no authentication. Proven by doing exactly that on loopback.

  G3  Device-error detection reads only the first line of output. The same
      assumption was wrong for Cisco IOS, which prints a caret marker on the
      line above its error. Whether ION does anything similar is unknown.
      Proven by sending a command the policy permits and the device rejects,
      then capturing the exact bytes.

DESIGN RULES
------------
* Every detector is isolated. One crashing must not cost the others their
  results; a crash is itself a finding and is recorded with its traceback.
* Nothing is inferred. A check that could not run records "not_run" and why,
  never a guess. Absence of evidence is logged as absence of evidence.
* Raw output is captured in full, deliberately. That is the only way to answer
  G1, and it means real device secrets land in probe/results/ and therefore in
  git. See the warning in .env.example.
* Read-only. Every command sent is one the policy already permits; nothing is
  configured, cleared or restarted on the device.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Load .env before importing anything from the package, and by explicit path:
# this script is meant to be run from /tmp or anywhere else, so nothing here
# may depend on the current working directory.
try:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
except ImportError:  # dotenv missing — fall back to a minimal parser
    _env_file = REPO / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
RESULTS = REPO / "probe" / "results" / RUN_ID
RAW = RESULTS / "raw"


def _normalise_env() -> None:
    """Map the probe's own target variables onto the internal names.

    ION_USERNAME and ION_PASSWORD are read directly by config.py now, so only
    the two variables that belong to the probe rather than the server need
    translating here.
    """
    aliases = {
        "ION_IP": "PRISMA_PROBE_ION_HOST",
        "ION_HOST": "PRISMA_PROBE_ION_HOST",
        "ION_ELEMENT": "PRISMA_PROBE_ELEMENT",
    }
    for short, canonical in aliases.items():
        value = (os.getenv(short) or "").strip()
        if value and not (os.getenv(canonical) or "").strip():
            os.environ[canonical] = value


_normalise_env()

# The two commands named for this exercise: one small, one large. The large one
# is what exercises truncation and the byte cap.
CMD_SMALL = "dump overview"
CMD_LARGE = "dump interface status all"
# Passes the `dump` family grammar (root + safe argument) and should be
# rejected by the device. That combination is what makes it a usable probe for
# G3: the policy lets it through, so the device's own error text comes back.
CMD_REJECTED = "dump zzprobenosuchsubcommand"

FINDINGS: list[dict] = []
CONSOLE: list[str] = []


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------
def log(message: str = "") -> None:
    print(message, flush=True)
    CONSOLE.append(message)


def write(relative: str, content: str) -> str:
    path = RESULTS / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return str(path.relative_to(RESULTS))


def record(gap: str, name: str, status: str, detail: dict) -> None:
    """status: proven | disproven | inconclusive | not_run | crashed."""
    FINDINGS.append({"gap": gap, "check": name, "status": status, **detail})
    log(f"  [{status.upper():12}] {gap} :: {name}")


def detector(gap: str, name: str):
    """Run a detector so that a crash becomes a finding rather than an exit."""
    def wrap(fn):
        def run(*args, **kwargs):
            log(f"\n--- {gap}: {name} ---")
            started = time.time()
            try:
                return fn(*args, **kwargs)
            except Exception:
                record(gap, name, "crashed", {
                    "elapsed_s": round(time.time() - started, 2),
                    "traceback": traceback.format_exc(),
                    "note": "the probe itself failed here; the gap is unresolved, not absent",
                })
                return None
        return run
    return wrap


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Candidate redaction patterns — what a text-level redactor WOULD catch.
# Deliberately kept here rather than imported: the point is to compare what the
# server actually does against what it would need to do.
# ---------------------------------------------------------------------------
CANDIDATE_PATTERNS = {
    "snmp_community": re.compile(r"(?i)\bcommunity[\s=:]+(\S+)"),
    "password_assignment": re.compile(r"(?i)\b(?:password|passwd)[\s=:]+(\S+)"),
    "secret_assignment": re.compile(r"(?i)\bsecret[\s=:]+(\S+)"),
    "key_assignment": re.compile(r"(?i)\b(?:key|pre-shared-key|psk)[\s=:]+(\S+)"),
    "token_assignment": re.compile(r"(?i)\btoken[\s=:]+(\S+)"),
    "unix_hash": re.compile(r"\$[0-9a-z]\$[^\s:]+"),
    "pem_block": re.compile(r"-----BEGIN [^-\n]*PRIVATE KEY-----"),
    "bearer": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    "basic_auth_url": re.compile(r"[a-z]+://[^/\s:]+:[^/\s@]+@"),
}


def scan_text(text: str) -> list[dict]:
    """Report every candidate-secret hit with its line number and value."""
    hits: list[dict] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in CANDIDATE_PATTERNS.items():
            for match in pattern.finditer(line):
                hits.append({
                    "pattern": label,
                    "line_number": number,
                    "line": line.strip(),
                    "matched": match.group(0),
                })
    return hits


# ---------------------------------------------------------------------------
# D0 — environment
# ---------------------------------------------------------------------------
@detector("G0", "environment")
def probe_environment() -> dict:
    from prisma_sdwan_mcp import config

    def version_of(name: str) -> str:
        try:
            module = __import__(name)
            return getattr(module, "__version__", "unknown")
        except Exception as exc:  # noqa: BLE001
            return f"NOT IMPORTABLE: {exc}"

    username, password, private_key, passphrase = config.get_ion_credentials()
    env = {
        "run_id": RUN_ID,
        "platform": platform.platform(),
        "system": platform.system(),
        "python": sys.version,
        "python_executable": sys.executable,
        "cwd": os.getcwd(),
        "repo": str(REPO),
        "os_user": getpass.getuser(),
        "home": os.path.expanduser("~"),
        "path_separator": os.sep,
        "versions": {name: version_of(name) for name in
                     ("netmiko", "paramiko", "fastmcp", "prisma_sase")},
        "ion_credentials": {
            "username_set": bool(username),
            "password_set": bool(password),
            "private_key_set": bool(private_key),
            "passphrase_set": bool(passphrase),
        },
        "controller_credentials": {
            name: bool(os.getenv(name))
            for name in ("PAN_CLIENT_ID", "PAN_CLIENT_SECRET", "PAN_TSG_ID")
        },
        "known_hosts": {
            "configured": config.get_ion_known_hosts(),
            "default_used": config.get_ion_known_hosts() is None,
            "default_path": os.path.expanduser("~/.ssh/known_hosts"),
            "default_exists": os.path.exists(os.path.expanduser("~/.ssh/known_hosts")),
        },
        "probe_target": {
            "host": os.getenv("PRISMA_PROBE_ION_HOST") or None,
            "element": os.getenv("PRISMA_PROBE_ELEMENT") or None,
        },
        "ssh_port": config.get_ion_ssh_port(),
        "max_output_bytes": config.get_ion_max_output_bytes(),
    }
    write("environment.json", json.dumps(env, indent=2))
    record("G0", "environment", "proven", {"summary": "captured", "file": "environment.json"})
    return env


@detector("G0", "ion_reachability")
def probe_reachability(host: str, port: int) -> bool:
    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=10):
            elapsed = round(time.time() - started, 2)
        record("G0", "ion_reachability", "proven",
               {"host": host, "port": port, "elapsed_s": elapsed, "reachable": True})
        return True
    except OSError as exc:
        record("G0", "ion_reachability", "disproven", {
            "host": host, "port": port, "reachable": False, "error": str(exc),
            "note": "every later detector that needs the device will report not_run",
        })
        return False


@detector("G0", "host_key_bootstrap")
def bootstrap_host_key(host: str, port: int) -> None:
    """Record the device's host key so the probe can connect unattended.

    The server has no first-use trust: an ION whose key is not already on
    record is refused. That is right for the server and pure friction for a
    one-shot probe, which would otherwise demand a manual `ssh-keyscan` step
    before it could do anything -- and `ssh-keyscan` itself returns nothing on
    devices that only offer ssh-rsa, which modern OpenSSH disables.

    So the probe fetches the key itself, through paramiko, and writes a
    known_hosts into its own results directory. Trust is not skipped, it is
    *recorded*: the fingerprint goes into findings.json, so what this run
    trusted is auditable afterwards even though nobody verified it at the time.

    An explicitly configured PRISMA_ION_KNOWN_HOSTS is never overwritten.
    """
    if os.getenv("PRISMA_ION_KNOWN_HOSTS", "").strip():
        record("G0", "host_key_bootstrap", "not_run", {
            "note": "PRISMA_ION_KNOWN_HOSTS is set explicitly; leaving it alone",
            "configured": os.environ["PRISMA_ION_KNOWN_HOSTS"],
        })
        return

    import base64
    import hashlib

    import paramiko

    sock = socket.create_connection((host, port), timeout=15)
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=15)
        key = transport.get_remote_server_key()
    finally:
        transport.close()

    entry_host = host if port == 22 else f"[{host}]:{port}"
    line = f"{entry_host} {key.get_name()} {key.get_base64()}\n"
    path = RESULTS / "known_hosts"
    path.write_text(line, encoding="utf-8", newline="\n")
    os.environ["PRISMA_ION_KNOWN_HOSTS"] = str(path)

    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(key.asbytes()).digest()
    ).decode().rstrip("=")
    record("G0", "host_key_bootstrap", "proven", {
        "host": entry_host,
        "key_type": key.get_name(),
        "key_bits": key.get_bits(),
        "fingerprint": fingerprint,
        "written_to": str(path),
        "note": "recorded automatically, NOT verified out of band. This is what the "
                "run trusted; check it against the device if the results matter.",
    })


# ---------------------------------------------------------------------------
# Tool invocation helper — drives the real MCP tool in-process
# ---------------------------------------------------------------------------
def _results_of(response: dict) -> list[dict]:
    """Pull the per-command results out of the v2 envelope.

    They live at run.results, not at the top level. Reading the wrong place
    returned an empty list, which the detectors then reported as "the device
    returned no output" -- a statement about the hardware invented from a
    parsing mistake, on a run where the tool had in fact worked.
    """
    if not isinstance(response, dict):
        return []
    for candidate in (
        (response.get("run") or {}).get("results"),
        response.get("results"),
        response.get("data"),
    ):
        if isinstance(candidate, list) and candidate:
            return [item for item in candidate if isinstance(item, dict)]
    return []


def tool_error(response: dict) -> str | None:
    """Return the tool's error code, if the call failed before reaching the device.

    Every device detector must check this first. A failed call carries an empty
    result list, and reading that as "the device returned nothing" turns a
    configuration mistake into a confident statement about the hardware -- which
    is exactly what the first live run did: three detectors reported
    "inconclusive, no output" when the real cause was a rejected credential set.
    An error is a `not_run`, never evidence.
    """
    if not isinstance(response, dict):
        return None
    code = response.get("code") or response.get("error")
    return str(code) if code else None


def call_run_commands(**kwargs) -> dict:
    """Call the real run_commands tool and return its parsed response."""
    from prisma_sdwan_mcp import runtime
    from prisma_sdwan_mcp.tools import cli as cli_tool

    runtime.initialize()
    raw = cli_tool.run_commands(**kwargs)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_unparsed": raw}
    return raw


@detector("G6", "direct_capture")
def probe_direct(host: str, port: int) -> None:
    """Talk to the device with netmiko directly, bypassing this project entirely.

    Every earlier run lost its device evidence to a bug in our own plumbing --
    first a credential check, then host-key wiring -- and each cost a full
    round trip to discover. This path shares no code with the MCP tool, so the
    device's actual behaviour is captured even when the tool cannot reach it.

    That separates two questions that kept getting confused: "is our wiring
    right" and "what does this hardware actually do". G1 and G3 only ever
    needed the second.
    """
    from netmiko import ConnectHandler

    username = os.getenv("PRISMA_ION_USERNAME")
    password = os.getenv("PRISMA_ION_PASSWORD")
    known_hosts = os.getenv("PRISMA_ION_KNOWN_HOSTS") or None
    if not username or not password:
        record("G6", "direct_capture", "not_run",
               {"note": "ION_USERNAME/ION_PASSWORD not set"})
        return

    kwargs: dict = {
        "device_type": "generic", "host": host, "port": port,
        "username": username, "password": password,
        "conn_timeout": 20, "auth_timeout": 20, "banner_timeout": 20,
        "allow_agent": False, "ssh_strict": True,
        "system_host_keys": known_hosts is None,
    }
    if known_hosts:
        kwargs["alt_host_keys"] = True
        kwargs["alt_key_file"] = known_hosts

    connection = ConnectHandler(**kwargs)
    captured: list[dict] = []
    try:
        prompt = str(connection.find_prompt())
        # The two named commands, the rejection, and a sweep of everything else
        # that plausibly carries configuration. G1 needs output containing a
        # secret to be settled at all, and `dump overview` / `dump interface
        # status all` carry none -- an ION is controller-managed, so its
        # configuration may simply never appear on the device CLI. Sampling
        # broadly is what turns "we did not happen to find one" into a
        # defensible answer. All are policy-permitted and read-only; anything
        # this firmware does not know just returns "unknown keyword", which is
        # itself more G3 evidence.
        sweep = (
            ("cfg", "dump config"),
            ("vpn", "dump vpn"),
            ("system", "inspect system"),
            ("snmp", "dump snmp"),
            ("users", "dump users"),
            ("auth", "dump authentication"),
            ("ipsec", "dump ipsec"),
            ("controller", "dump controller"),
        )
        for label, command in (("small", CMD_SMALL), ("large", CMD_LARGE),
                               ("rejected", CMD_REJECTED), *sweep):
            started = time.time()
            try:
                output = str(connection.send_command(command, read_timeout=120))
                error = None
            except Exception as exc:  # noqa: BLE001 — capture, do not abort
                output, error = "", f"{type(exc).__name__}: {exc}"
            write(f"raw/direct_{label}.txt", output)
            hits = scan_text(output)
            lines = output.splitlines()
            first_meaningful = next(
                (i for i, line in enumerate(lines) if not re.match(r"^[\s^~]*$", line)),
                None,
            )
            captured.append({
                "label": label, "command": command,
                "elapsed_s": round(time.time() - started, 2),
                "error": error,
                "bytes": len(output.encode("utf-8")),
                "lines": len(lines),
                "candidate_secret_hits": hits,
                "candidate_hit_count": len(hits),
                # G3 evidence: is the error on line one, or is something above it?
                "first_lines_repr": [repr(line) for line in lines[:6]],
                "first_meaningful_line_index": first_meaningful,
                "has_preamble_above_first_content": bool(
                    first_meaningful is not None and first_meaningful > 0
                ),
            })
    finally:
        connection.disconnect()

    record("G6", "direct_capture", "proven", {
        "prompt_repr": repr(prompt),
        "note": "captured without any of this project's code in the path; use it to "
                "answer G1/G3 even when the MCP tool failed",
        "commands": captured,
    })


# ---------------------------------------------------------------------------
# G1 — does redaction reach CLI text at all?
# ---------------------------------------------------------------------------
@detector("G1", "text_redaction")
def probe_redaction(host: str) -> None:
    from prisma_sdwan_mcp.safety import ResponseSafety

    per_command: list[dict] = []
    for label, command in (("small", CMD_SMALL), ("large", CMD_LARGE)):
        started = time.time()
        response = call_run_commands(host=host, commands=[command])
        elapsed = round(time.time() - started, 2)

        failure = tool_error(response)
        if failure:
            write(f"raw/{label}_response.json", json.dumps(response, indent=2))
            record("G1", "text_redaction", "not_run", {
                "command": command,
                "tool_error": failure,
                "message": response.get("message"),
                "note": "the call never reached the device, so nothing here says anything "
                        "about redaction. Fix the error and re-run.",
            })
            return

        write(f"raw/{label}_response.json", json.dumps(response, indent=2))
        results = _results_of(response)
        output = results[0].get("output", "") if results else ""
        write(f"raw/{label}_output.txt", output)

        hits = scan_text(output)
        # The real redactor, applied to the real response, exactly as the
        # server applies it.
        redacted = ResponseSafety().redact(response)
        changed = redacted != response
        redacted_json = json.dumps(redacted, indent=2, default=str)
        write(f"raw/{label}_after_safety_redact.json", redacted_json)

        per_command.append({
            "label": label,
            "command": command,
            "elapsed_s": elapsed,
            "error": response.get("code") or response.get("error"),
            "output_bytes": len(output.encode("utf-8")),
            "output_lines": len(output.splitlines()),
            "candidate_secret_hits": hits,
            "candidate_hit_count": len(hits),
            "safety_redact_changed_anything": changed,
            "redacted_marker_count": redacted_json.count("[REDACTED]"),
            "response_keys": sorted(response.keys()) if isinstance(response, dict) else None,
        })

    total_hits = sum(entry["candidate_hit_count"] for entry in per_command)
    any_changed = any(entry["safety_redact_changed_anything"] for entry in per_command)

    if total_hits and not any_changed:
        status, verdict = "proven", (
            "Candidate secrets are present in ION output and safety.redact() changed "
            "nothing. Key-based redaction cannot reach text values; a text-level "
            "redactor is required."
        )
    elif total_hits and any_changed:
        status, verdict = "inconclusive", (
            "Secrets present AND redaction changed something — inspect which keys it "
            "touched and whether the text itself survived."
        )
    elif not total_hits:
        status, verdict = "inconclusive", (
            "No candidate secrets in these two commands' output, so this run cannot "
            "prove or disprove the gap. The mechanism is still key-based; try a "
            "command whose output carries configuration."
        )
    else:
        status, verdict = "inconclusive", "unexpected combination — read the raw files"

    record("G1", "text_redaction", status, {"verdict": verdict, "commands": per_command})


# ---------------------------------------------------------------------------
# G2 — unauthenticated HTTP exposure, on loopback only
# ---------------------------------------------------------------------------
@detector("G2", "unauthenticated_http")
def probe_transport_gate(host: str) -> None:
    port = free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    server = subprocess.Popen(
        [sys.executable, "-m", "prisma_sdwan_mcp.server",
         "--transport", "streamable-http", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    detail: dict = {
        "bound": f"127.0.0.1:{port}",
        "reachable_from": "this machine only — deliberately not 0.0.0.0",
        "auth_configured": False,
    }
    try:
        # Wait for the port to accept, rather than sleeping a fixed guess.
        deadline = time.time() + 45
        listening = False
        while time.time() < deadline:
            if server.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    listening = True
                    break
            except OSError:
                time.sleep(0.5)
        detail["server_started"] = listening

        if not listening:
            out, err = server.communicate(timeout=10)
            detail.update({"stdout": out[-4000:], "stderr": err[-4000:]})
            record("G2", "unauthenticated_http", "not_run",
                   {**detail, "note": "server never bound; gap unresolved"})
            return

        async def exercise() -> dict:
            from fastmcp import Client
            # No credentials, no token, no headers. If this works, there is no
            # authentication in front of the tool.
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                tools = sorted(t.name for t in await client.list_tools())
                outcome: dict = {
                    "connected_without_credentials": True,
                    "tools_visible": tools,
                    "run_commands_exposed": "run_commands" in tools,
                }
                if "run_commands" in tools:
                    started = time.time()
                    called = await client.call_tool(
                        "run_commands",
                        {"host": host, "commands": [CMD_SMALL]},
                        raise_on_error=False,
                    )
                    payload = called.structured_content or called.data
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except json.JSONDecodeError:
                            payload = {"_unparsed": payload[:2000]}
                    reached = bool(
                        isinstance(payload, dict)
                        and not payload.get("code")
                        and (payload.get("results") or payload.get("data"))
                    )
                    outcome.update({
                        "called_run_commands_anonymously": True,
                        "reached_the_ion": reached,
                        "elapsed_s": round(time.time() - started, 2),
                        "response_excerpt": json.dumps(payload, default=str)[:2000],
                    })
                return outcome

        detail.update(asyncio.run(exercise()))

        if detail.get("reached_the_ion"):
            status, verdict = "proven", (
                "An anonymous HTTP client listed run_commands and used it to reach the "
                "ION over SSH with the server's stored credentials. Over a non-loopback "
                "bind this is an open SSH proxy into the WAN. A registration gate and a "
                "socket-transport gate are both missing."
            )
        elif detail.get("run_commands_exposed"):
            status, verdict = "proven", (
                "An anonymous HTTP client listed run_commands with no authentication. "
                "The call did not reach the device in this run — see response_excerpt "
                "for why — but the tool is exposed unauthenticated regardless."
            )
        else:
            status, verdict = "disproven", "run_commands was not exposed to an anonymous client"
        record("G2", "unauthenticated_http", status, {**detail, "verdict": verdict})
    finally:
        server.terminate()
        try:
            out, err = server.communicate(timeout=15)
            write("raw/http_server_stdout.txt", out or "")
            write("raw/http_server_stderr.txt", err or "")
        except subprocess.TimeoutExpired:
            server.kill()


# ---------------------------------------------------------------------------
# G3 — what a real ION rejection looks like
# ---------------------------------------------------------------------------
@detector("G3", "device_error_shape")
def probe_error_detection(host: str) -> None:
    from prisma_sdwan_mcp.cli.policy import validate_batch

    decision = validate_batch([CMD_REJECTED])
    if not decision.allowed:
        record("G3", "device_error_shape", "not_run", {
            "command": CMD_REJECTED,
            "note": "the policy refused the probe command, so the device never saw it. "
                    "Pick a command that passes the grammar but the device rejects.",
            "policy_decision": str(decision)[:1000],
        })
        return

    response = call_run_commands(host=host, commands=[CMD_REJECTED])
    write("raw/rejected_response.json", json.dumps(response, indent=2))

    failure = tool_error(response)
    if failure:
        record("G3", "device_error_shape", "not_run", {
            "command": CMD_REJECTED,
            "tool_error": failure,
            "message": response.get("message"),
            "note": "the call never reached the device. Its error shape is still unknown; "
                    "this is not 'the device returned nothing'.",
        })
        return

    results = _results_of(response)
    entry = results[0] if results else {}
    output = entry.get("output") or entry.get("error") or ""
    write("raw/rejected_output.txt", output)

    lines = output.splitlines()
    # Read the tool's own verdict rather than re-deriving it. The detector used
    # to call _is_device_error(output) with no prompt argument, which is not how
    # the tool calls it, so it reported "detection did not fire" on a run where
    # the tool had classified the rejection correctly -- the probe disagreeing
    # with reality because it was testing a different thing.
    detected = entry.get("status") == "error"
    reported_ok = entry.get("status")

    # The exact question: is the error on the first line, or is something
    # printed above it? repr() so whitespace and control bytes are visible.
    preamble = []
    for number, line in enumerate(lines[:6], start=1):
        preamble.append({
            "line_number": number,
            "repr": repr(line),
            "is_blank_or_marker": bool(re.match(r"^[\s^~]*$", line)),
        })

    first_meaningful = next(
        (i for i, line in enumerate(lines) if not re.match(r"^[\s^~]*$", line)), None
    )
    has_preamble = first_meaningful is not None and first_meaningful > 0

    echoed_above_error = bool(lines) and any(
        CMD_REJECTED in line for line in lines[:2]
    )
    if echoed_above_error and not detected:
        status, verdict = "proven", (
            f"The device printed {first_meaningful} non-substantive line(s) before its "
            "error text, and _is_device_error() — which reads only the first line — "
            "missed it. A rejected command is being reported as successful, exactly as "
            "it was on Cisco IOS."
        )
    elif echoed_above_error and detected:
        status, verdict = "disproven", (
            "The device echoes the prompt and command above its error, and the tool "
            "still classified the command as failed. The echo-skipping fix holds on "
            "real output."
        )
    elif not lines:
        status, verdict = "inconclusive", (
            "The device returned no output for the rejected command, so its error shape "
            "is still unknown. Try a different invalid command."
        )
    elif detected:
        status, verdict = "disproven", (
            "The error is on the first line and detection fired. The first-line "
            "assumption holds for this device and this command."
        )
    else:
        status, verdict = "proven", (
            "Detection did not fire even though the command was rejected. The error "
            "vocabulary in _DEVICE_ERROR does not match what this device prints — see "
            "raw/rejected_output.txt for the wording to add."
        )

    record("G3", "device_error_shape", status, {
        "command": CMD_REJECTED,
        "verdict": verdict,
        "tool_reported_ok": reported_ok,
        "is_device_error_returned": detected,
        "line_count": len(lines),
        "first_meaningful_line_index": first_meaningful,
        "echo_above_the_error": echoed_above_error,
        "first_lines_repr": preamble,
        "full_output_repr": repr(output[:4000]),
    })


# ---------------------------------------------------------------------------
# Supporting capture — truncation and the name-resolution path
# ---------------------------------------------------------------------------
@detector("G4", "truncation_and_caps")
def probe_truncation(host: str) -> None:
    # The large command produced ~11 KB against a 40 KB cap, so truncation was
    # never actually exercised -- the check reported "proven" having tested
    # nothing. Lower the cap below the known output size so the path runs, then
    # put it back. This is the probe's own configuration, not the device's.
    previous = os.environ.get("PRISMA_ION_MAX_OUTPUT_BYTES")
    os.environ["PRISMA_ION_MAX_OUTPUT_BYTES"] = "4096"
    try:
        response = call_run_commands(host=host, commands=[CMD_LARGE])
    finally:
        if previous is None:
            os.environ.pop("PRISMA_ION_MAX_OUTPUT_BYTES", None)
        else:
            os.environ["PRISMA_ION_MAX_OUTPUT_BYTES"] = previous
    failure = tool_error(response)
    if failure:
        record("G4", "truncation_and_caps", "not_run", {
            "tool_error": failure, "message": response.get("message"),
            "note": "the call never reached the device",
        })
        return
    results = _results_of(response)
    entry = results[0] if results else {}
    output = entry.get("output", "")
    truncated = bool(entry.get("truncated"))
    record("G4", "truncation_and_caps", "proven" if truncated else "inconclusive", {
        "command": CMD_LARGE,
        "cap_applied_bytes": 4096,
        "result_fields": sorted(entry.keys()) if isinstance(entry, dict) else None,
        "output_bytes": len(output.encode("utf-8")),
        "declared_truncated": truncated,
        "declared_output_bytes": entry.get("output_bytes"),
        "declared_output_bytes_total": entry.get("output_bytes_total"),
        "envelope_keys": sorted(response.keys()) if isinstance(response, dict) else None,
        "verdict": ("Truncation fired and was declared; check that a caller can tell a cut "
                    "answer from a whole one from these fields alone."
                    if truncated else
                    "Output fitted inside the lowered cap, so truncation still was not "
                    "exercised. Lower the cap further or use a larger command."),
    })


@detector("G5", "name_resolution")
def probe_name_resolution(element: str | None) -> None:
    if not element:
        record("G5", "name_resolution", "not_run", {
            "note": "PRISMA_PROBE_ELEMENT is unset, so the controller-backed "
                    "name-to-address path was not exercised. This is not evidence "
                    "that it works.",
        })
        return
    started = time.time()
    response = call_run_commands(element=element, commands=[CMD_SMALL])
    results = _results_of(response)
    record("G5", "name_resolution", "proven" if results else "inconclusive", {
        "element": element,
        "elapsed_s": round(time.time() - started, 2),
        "error": response.get("code") or response.get("error"),
        "resolved": {k: response.get(k) for k in
                     ("host", "address", "element_name", "element_id", "site_id")
                     if k in (response or {})},
        "response_excerpt": json.dumps(response, default=str)[:3000],
    })


# ---------------------------------------------------------------------------
def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    log("=" * 72)
    log(f"prisma-sdwan-mcp diagnostic probe   run {RUN_ID}")
    log(f"results -> {RESULTS}")
    log("=" * 72)
    log("This captures FULL RAW DEVICE OUTPUT, including any secrets the ION")
    log("prints. Those files are committed for review. Treat this repo as")
    log("sensitive after running.")

    environment = probe_environment() or {}

    host = os.getenv("PRISMA_PROBE_ION_HOST", "").strip()
    element = os.getenv("PRISMA_PROBE_ELEMENT", "").strip() or None
    if not host:
        log("\nNothing to probe: ION_IP is not set.")
        log("Put three lines in .env and re-run:")
        log("    ION_IP=10.0.0.1")
        log("    ION_USERNAME=admin")
        log("    ION_PASSWORD=...")
        record("G0", "probe_target", "not_run", {
            "note": "ION_IP is unset, so every device-dependent detector was skipped. "
                    "Set ION_IP, ION_USERNAME and ION_PASSWORD in .env and re-run.",
        })
    else:
        port = int(os.getenv("PRISMA_ION_SSH_PORT", "22") or 22)
        if probe_reachability(host, port):
            bootstrap_host_key(host, port)
            # Device facts first, through a path that shares no code with the
            # tool, so a bug in our wiring cannot cost this run its evidence.
            probe_direct(host, port)
            probe_redaction(host)
            probe_error_detection(host)
            probe_truncation(host)
            probe_transport_gate(host)
            probe_name_resolution(element)
        else:
            for gap, name in (("G1", "text_redaction"), ("G3", "device_error_shape"),
                              ("G4", "truncation_and_caps"), ("G5", "name_resolution")):
                record(gap, name, "not_run", {"note": "ION unreachable from this host"})
            # The transport gate needs the server, not the device — still worth running.
            probe_transport_gate(host)

    summary = {
        "run_id": RUN_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "platform": environment.get("platform"),
        "target_host": host or None,
        "status_counts": {
            status: sum(1 for f in FINDINGS if f["status"] == status)
            for status in ("proven", "disproven", "inconclusive", "not_run", "crashed")
        },
        "findings": FINDINGS,
    }
    write("findings.json", json.dumps(summary, indent=2, default=str))
    write("console.log", "\n".join(CONSOLE))

    log("\n" + "=" * 72)
    log("SUMMARY")
    for finding in FINDINGS:
        log(f"  {finding['status']:12} {finding['gap']:3} {finding['check']}")
    log(f"\ncounts: {summary['status_counts']}")
    log(f"\nCommit probe/results/{RUN_ID}/ and pull it for review.")
    log("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
