import logging
import re
from pathlib import Path

from gunicorn.glogging import Logger as GunicornLogger


def _label(value):
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", str(value))[:100]


def safe_exception_context(exc_info):
    """Retain exception type and source locations without messages or locals."""
    exc_type, exception, trace = exc_info
    details = f"exception={_label(getattr(exc_type, '__name__', 'unknown'))}"
    sqlstate = getattr(exception, "sqlstate", None) or getattr(
        getattr(exception, "__cause__", None), "sqlstate", None
    )
    if isinstance(sqlstate, str) and re.fullmatch(r"[A-Z0-9]{5}", sqlstate):
        details += f" sqlstate={sqlstate}"
    stack = []
    while trace is not None:
        code = trace.tb_frame.f_code
        stack.append(f"{_label(Path(code.co_filename).name)}:{_label(code.co_name)}:{trace.tb_lineno}")
        trace = trace.tb_next
    if stack:
        details += " stack=" + " > ".join(stack[-8:])
    return details


class SafeExceptionLogFilter(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            record.msg = "Application error " + safe_exception_context(record.exc_info)
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


class SafeGunicornLogFilter(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            record.msg = "HTTP worker error " + safe_exception_context(record.exc_info)
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        elif "Error handling request" in str(record.msg):
            record.msg = "HTTP worker could not complete a request"
            record.args = ()
        return True


class SafeGunicornLogger(GunicornLogger):
    def setup(self, cfg):
        super().setup(cfg)
        self.error_log.addFilter(SafeGunicornLogFilter())


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
        details = safe_exception_context(record.exc_info) if record.exc_info else "exception=none"
        record.msg = f"HTTP event method={method} view={view_name} status={status} {details}"
        request_id = getattr(request, "request_id", None)
        if isinstance(request_id, str) and re.fullmatch(r"[a-f0-9]{32}", request_id):
            record.msg += f" request_id={request_id}"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.request = None
        return True
