"""Raw ION CLI capture — no parsing, no prompt-detection, just bytes in a file.

Bypasses netmiko's send_command (which waits for a known prompt pattern and
strips it). ION CLI output is not consistently structured, so instead this
opens a raw paramiko shell, sends the command, and reads until the channel
goes idle. Whatever the device sends -- banner, gibberish, the command echo,
the real output -- all of it lands in the output file untouched.

Usage:
    ION_HOST=10.64.167.4 ION_USERNAME=ntt-dd ION_PASSWORD='...' \
        python capture.py "dump overview"

Credentials are read from env vars only. Never hardcode them here -- this
folder gets pushed to github.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko

CONNECT_TIMEOUT = 10
IDLE_SECONDS = 3.0   # stop once the channel has been quiet this long
MAX_SECONDS = 60.0   # hard ceiling regardless of idling
RECV_CHUNK = 65535

OUTPUT_DIR = Path(__file__).parent / "output"


def read_until_idle(chan: paramiko.Channel) -> bytes:
    data = b""
    last_recv = time.monotonic()
    start = last_recv
    while True:
        now = time.monotonic()
        if now - start > MAX_SECONDS:
            break
        if chan.recv_ready():
            chunk = chan.recv(RECV_CHUNK)
            if not chunk:
                break
            data += chunk
            last_recv = now
        else:
            if now - last_recv > IDLE_SECONDS:
                break
            time.sleep(0.1)
    return data


def capture(host: str, username: str, password: str, command: str) -> Path:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=username,
        password=password,
        timeout=CONNECT_TIMEOUT,
        allow_agent=False,
        look_for_keys=False,
    )

    chan = client.invoke_shell()
    raw = read_until_idle(chan)  # banner / login gibberish, captured as-is

    chan.send(command + "\n")
    raw += read_until_idle(chan)

    client.close()

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_command = command.replace(" ", "_").replace("/", "_")
    out_path = OUTPUT_DIR / f"{stamp}_{host}_{safe_command}.raw.txt"
    out_path.write_bytes(raw)
    return out_path


def main() -> None:
    host = os.environ.get("ION_HOST", "10.64.167.4")
    username = os.environ["ION_USERNAME"]
    password = os.environ["ION_PASSWORD"]
    command = sys.argv[1] if len(sys.argv) > 1 else "dump overview"

    out_path = capture(host, username, password, command)
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
