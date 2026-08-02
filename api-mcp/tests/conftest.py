import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from dotenv import load_dotenv


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))
load_dotenv(PACKAGE_ROOT / ".env")


@dataclass
class FakeSDKResponse:
    cgx_status: bool
    cgx_content: object
    status_code: int = 200


@pytest.fixture
def fake_response():
    def make_response(content, status_code=200, cgx_status=True):
        return FakeSDKResponse(
            cgx_status=cgx_status,
            cgx_content=content,
            status_code=status_code,
        )

    return make_response


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: requires PAN_CLIENT_ID, PAN_CLIENT_SECRET, and PAN_TSG_ID",
    )


def pytest_collection_modifyitems(config, items):
    credentials_present = all(
        os.getenv(name)
        for name in ("PAN_CLIENT_ID", "PAN_CLIENT_SECRET", "PAN_TSG_ID")
    )
    if credentials_present:
        return

    skip_live = pytest.mark.skip(reason="live tenant credentials are not configured")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)