from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

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
