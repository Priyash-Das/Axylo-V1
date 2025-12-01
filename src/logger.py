from datetime import datetime
import os
import sys
import logging
import json
import re
from typing import Any, Optional
import contextvars

_COLORS = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "VOICE": "\033[94m",
    "TTS": "\033[92m",
    "AGENT": "\033[96m",
    "SEARCH": "\033[95m",
    "TOOLS": "\033[93m",
    "ERROR": "\033[91m",
    "DEBUG": "\033[90m",
    "INFO": "\033[97m",
    "USER": "\033[38;5;214m",
    "WARNING": "\033[93m",
}

LOG_FORMAT = os.getenv("LOG_FORMAT", "").lower()   
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "")

_LEVEL_MAP = {
    "NOTSET": logging.NOTSET,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_current_level = _LEVEL_MAP.get(LOG_LEVEL, logging.INFO)

_app_logger = logging.getLogger("ai_agent")
_app_logger.setLevel(_current_level)

if not _app_logger.handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(_current_level)
    stream_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    stream_handler.setFormatter(stream_formatter)
    _app_logger.addHandler(stream_handler)

if LOG_FILE:
    has_file = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", "") == os.path.abspath(LOG_FILE)
        for h in _app_logger.handlers
    )
    if not has_file:
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        except Exception:
            pass
        fh = logging.FileHandler(LOG_FILE)
        fh.setLevel(_current_level)
        fh.setFormatter(stream_formatter)
        _app_logger.addHandler(fh)

logging.getLogger("urllib3").setLevel(logging.WARNING)

def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|apikey|token|secret)[\s:=]+([A-Za-z0-9\-\._]+)"),
    re.compile(r"(?i)(bearer)\s+([A-Za-z0-9\-\._]+)"),
    re.compile(r"(?i)(ssh-rsa|ssh-ed25519)\s+[A-Za-z0-9+/=]+"),
]

def mask_secrets(text: str) -> str:
    if not text:
        return text
    s = str(text)
    for pat in _SECRET_PATTERNS:
        s = pat.sub(lambda m: f"{m.group(1)}=****", s)
    if len(s) > 2000:
        s = s[:2000] + " ...[truncated]"
    return s

_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)

def set_request_id(request_id: Optional[str]) -> None:
    """
    Set the current request ID for correlation across logs.
    Pass None to clear.
    """
    _request_id_var.set(request_id)

def get_request_id() -> Optional[str]:
    """
    Get the current request ID, or None if not set.
    """
    return _request_id_var.get()

def _should_log(level: int) -> bool:
    return level >= _current_level

def _format_colored(tag: str, *parts: Any) -> str:
    """
    Format a colored console log line with optional request ID.
    """
    color = _COLORS.get(tag.upper(), _COLORS["INFO"])
    reset = _COLORS["RESET"]
    message = " ".join(str(p) for p in parts)
    message = mask_secrets(message)

    req_id = get_request_id()
    if req_id:
        prefix = f"[REQ {req_id}] "
    else:
        prefix = ""

    return f"{color}[{tag.upper()}] {prefix}{message}{reset}"

def _format_json(tag: str, levelname: str, *parts: Any) -> str:
    """
    JSON log format: good for log aggregation.
    """
    message = " ".join(str(p) for p in parts)
    message = mask_secrets(message)

    payload = {
        "timestamp": _now_str(),
        "tag": tag.upper(),
        "level": levelname,
        "message": message,
    }

    req_id = get_request_id()
    if req_id:
        payload["request_id"] = req_id

    return json.dumps(payload, ensure_ascii=False)

def _emit(
    tag: str,
    levelname: str,
    levelnum: int,
    to_stderr: bool,
    *parts: Any,
) -> None:
    """
    Core logging dispatcher.
    - Handles console/file output.
    - Applies JSON or colored format.
    - Forwards to underlying _app_logger.
    """
    if not _should_log(levelnum):
        return

    if LOG_FORMAT == "json":
        out = _format_json(tag, levelname, *parts)
        stream = sys.stderr if to_stderr else sys.stdout
        print(out, file=stream)

        try:
            msg = mask_secrets(" ".join(str(p) for p in parts))
            logger_method = getattr(_app_logger, levelname.lower(), _app_logger.info)
            logger_method(f"[{tag.upper()}] {msg}")
        except Exception:
            pass
        return

    out = _format_colored(tag, *parts)
    stream = sys.stderr if to_stderr else sys.stdout
    print(out, file=stream)

    try:
        msg = mask_secrets(" ".join(str(p) for p in parts))
        logger_method = getattr(_app_logger, levelname.lower(), _app_logger.info)
        logger_method(f"[{tag.upper()}] {msg}")
    except Exception:
        pass

def voice(*parts: Any) -> None:
    """Voice input / listening related logs."""
    _emit("VOICE", "INFO", logging.INFO, False, *parts)

def tts(*parts: Any) -> None:
    """Text-to-speech related logs."""
    _emit("TTS", "INFO", logging.INFO, False, *parts)

def agent(*parts: Any) -> None:
    """Agent reasoning / response logs."""
    _emit("AGENT", "INFO", logging.INFO, False, *parts)

def search(*parts: Any) -> None:
    """Web/search engine related logs."""
    _emit("SEARCH", "INFO", logging.INFO, False, *parts)

def tools(*parts: Any) -> None:
    """Desktop automation / tools logs."""
    _emit("TOOLS", "INFO", logging.INFO, False, *parts)

def user(*parts: Any) -> None:
    """User-facing / transcript logs."""
    _emit("USER", "INFO", logging.INFO, False, *parts)

def debug(*parts: Any) -> None:
    """Debug-level logs."""
    _emit("DEBUG", "DEBUG", logging.DEBUG, False, *parts)

def info(*parts: Any) -> None:
    """General info logs."""
    _emit("INFO", "INFO", logging.INFO, False, *parts)

def warning(*parts: Any) -> None:
    """Warnings (non-fatal problems)."""
    _emit("WARNING", "WARNING", logging.WARNING, True, *parts)

def error(*parts: Any) -> None:
    """Errors (exceptions, failures)."""
    _emit("ERROR", "ERROR", logging.ERROR, True, *parts)
