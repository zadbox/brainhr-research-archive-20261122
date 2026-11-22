"""Keep OAuth callback credentials out of Uvicorn access logs."""

import logging
import re


CALLBACK_PATH = "/api/v1/auth/google/callback"
_CALLBACK_QUERY = re.compile(r"(/api/v1/auth/google/callback)\?[^\s\"]*")


class GoogleCallbackAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path, separator, _ = args[2].partition("?")
            if separator and path == CALLBACK_PATH:
                record.args = (*args[:2], path, *args[3:])
        elif isinstance(record.msg, str):
            record.msg = _CALLBACK_QUERY.sub(r"\1", record.msg)
        return True


def install_google_callback_access_log_filter() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, GoogleCallbackAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(GoogleCallbackAccessLogFilter())
