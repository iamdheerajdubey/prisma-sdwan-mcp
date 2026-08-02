import os

from dotenv import load_dotenv


load_dotenv()

DEFAULT_CONTROLLER = "https://api.sase.paloaltonetworks.com"
DEFAULT_MAX_RESPONSE_BYTES = 40960


def get_controller() -> str:
    return os.getenv("PAN_CONTROLLER") or DEFAULT_CONTROLLER


def get_credentials() -> tuple[str | None, str | None, str | None]:
    return (
        os.getenv("PAN_CLIENT_ID"),
        os.getenv("PAN_CLIENT_SECRET"),
        os.getenv("PAN_TSG_ID"),
    )


def get_max_response_bytes() -> int:
    raw_value = os.getenv("PRISMA_MCP_MAX_RESPONSE_BYTES")
    if raw_value is None:
        return DEFAULT_MAX_RESPONSE_BYTES
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_RESPONSE_BYTES
    return value if value > 0 else DEFAULT_MAX_RESPONSE_BYTES


def get_output_dir() -> str:
    return os.getenv("PRISMA_MCP_OUTPUT_DIR") or os.getcwd()