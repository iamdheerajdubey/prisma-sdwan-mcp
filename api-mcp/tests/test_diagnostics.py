import io
import json

from prisma_sdwan_mcp.formatting import internal_error
from prisma_sdwan_mcp.server import CleanStderr


def test_clean_stderr_only_filters_after_shutdown():
    output = io.StringIO()
    stream = CleanStderr(output)

    stream.write("Traceback from a normal tool call\n")
    stream.begin_shutdown()
    stream.write("Traceback (most recent call last)\n")
    stream.write("shutdown complete\n")

    assert output.getvalue() == "Traceback from a normal tool call\nshutdown complete\n"


def test_internal_error_is_safe_and_logs_traceback(caplog):
    with caplog.at_level("ERROR"):
        try:
            raise RuntimeError("secret internal detail")
        except RuntimeError as error:
            result = json.loads(internal_error("diagnostic_tool", error))

    assert result == {
        "code": "internal_error",
        "message": "an unexpected server error occurred",
        "tool": "diagnostic_tool",
        "status_code": 500,
        "retryable": True,
    }
    assert "secret internal detail" in caplog.text