import logging
import re
from pathlib import Path


def _label(value):
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", str(value))[:100]


class SafeRequestLogFilter(logging.Filter):
    """Keep useful failure context without URLs, payloads, or exception values."""

    def filter(self, record):
        request = getattr(record, "request", None)
        method = getattr(request, "method", "unknown")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            method = "unknown"
        match = getattr(request, "resolver_match", None)
        view_name = _label(getattr(match, "view_name", None) or "unresolved")
        status = getattr(record, "status_code", "unknown")
        if not isinstance(status, int):
            status = "unknown"
        exception = "none"
        stack = []
        if record.exc_info:
            exc_type, _, trace = record.exc_info
            exception = _label(getattr(exc_type, "__name__", "unknown"))
            while trace is not None:
                code = trace.tb_frame.f_code
                stack.append(
                    f"{_label(Path(code.co_filename).name)}:{_label(code.co_name)}:{trace.tb_lineno}"
                )
                trace = trace.tb_next
        record.msg = f"HTTP event method={method} view={view_name} status={status} exception={exception}"
        if stack:
            record.msg += " stack=" + " > ".join(stack[-8:])
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.request = None
        return True
