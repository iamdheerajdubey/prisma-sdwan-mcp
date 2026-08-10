from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load the .env that sits beside the installed package's repository root, not
# whatever happens to be under the current working directory. Bare
# `load_dotenv()` searches upward from the CWD, so the same install picks up
# different configuration -- or none at all -- depending on where it was
# launched from: a systemd unit with its own WorkingDirectory, a probe run out
# of /tmp, or `cd /` before starting the server all silently lose the file.
# An explicit path behaves identically on Linux and Windows.
#
# Real environment variables still win: `override=False` is the default, so a
# container's injected secrets are never overwritten by a stale checked-out
# .env, and PRISMA_ENV_FILE redirects the lookup when one host serves several
# configurations.
_ENV_FILE = os.getenv("PRISMA_ENV_FILE") or (Path(__file__).resolve().parents[1] / ".env")
load_dotenv(_ENV_FILE)
# Keep the CWD-relative search as a fallback so an install laid out
# differently (site-packages, a zipapp) still finds a .env placed next to it.
load_dotenv()

DEFAULT_CONTROLLER = "https://api.sase.paloaltonetworks.com"
DEFAULT_MAX_RESPONSE_BYTES = 40960
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
DEFAULT_MAX_FANOUT = 100


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_controller() -> str:
    return os.getenv("PAN_CONTROLLER", DEFAULT_CONTROLLER).strip() or DEFAULT_CONTROLLER


def get_credentials() -> tuple[str | None, str | None, str | None]:
    return (
        os.getenv("PAN_CLIENT_ID"),
        os.getenv("PAN_CLIENT_SECRET"),
        os.getenv("PAN_TSG_ID"),
    )


def get_max_response_bytes() -> int:
    return _int_env("MCP_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES)


def get_default_page_size() -> int:
    return min(_int_env("MCP_DEFAULT_PAGE_SIZE", DEFAULT_PAGE_SIZE), get_max_page_size())


def get_max_page_size() -> int:
    return _int_env("MCP_MAX_PAGE_SIZE", MAX_PAGE_SIZE)


def get_max_fanout() -> int:
    return _int_env("MCP_MAX_FANOUT", DEFAULT_MAX_FANOUT)


def expert_tool_enabled() -> bool:
    return _bool_env("MCP_EXPERT_TOOL_ENABLED", True)


def allow_unverified_compat() -> bool:
    return _bool_env("MCP_ALLOW_UNVERIFIED_COMPAT", False)


def data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def get_ion_credentials() -> tuple[str | None, str | None, str | None, str | None]:
    return (
        os.getenv("PRISMA_ION_USERNAME"),
        os.getenv("PRISMA_ION_PASSWORD"),
        os.getenv("PRISMA_ION_PRIVATE_KEY"),
        os.getenv("PRISMA_ION_PRIVATE_KEY_PASSPHRASE"),
    )


def get_ion_known_hosts() -> str | None:
    """Path to the known_hosts file used to verify ION host keys.

    Unset means "use the SSH client's own default", which is
    ``~/.ssh/known_hosts`` on both Linux and Windows -- paramiko expands the
    home directory per-platform, so no path is hard-coded either way.

    Setting it explicitly is what makes a container or a fresh server usable:
    there is no first-use trust, so without a readable known_hosts listing the
    device, every connection fails and the only remedy would be an interactive
    ``ssh`` login as the same OS user. ``~`` is expanded here because the SSH
    layer is handed a plain path and does not expand it itself.
    """
    value = (os.getenv("PRISMA_ION_KNOWN_HOSTS") or "").strip()
    return os.path.expanduser(value) if value else None


def get_ion_ssh_port() -> int:
    return _int_env("PRISMA_ION_SSH_PORT", 22, minimum=1)


def get_ion_probe_timeout() -> float:
    return float(_int_env("PRISMA_ION_PROBE_TIMEOUT", 3, minimum=1))


def get_ion_connect_timeout() -> float:
    return float(_int_env("PRISMA_ION_CONNECT_TIMEOUT", 10, minimum=1))


def get_ion_read_timeout() -> float:
    return float(_int_env("PRISMA_ION_READ_TIMEOUT", 300, minimum=1))


def get_ion_max_output_bytes() -> int:
    return _int_env("PRISMA_ION_MAX_OUTPUT_BYTES", 40960)


def get_ion_max_commands() -> int:
    return _int_env("PRISMA_ION_MAX_COMMANDS", 10)
