import logging
import sys
import copy
import re
from src.app.core.config import settings


def _redact(value: str) -> str:
    value = re.sub(r"(sk-[A-Za-z0-9_-]{10,})", "[REDACTED_API_KEY]", value)
    value = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]{10,}", r"\1[REDACTED_TOKEN]", value, flags=re.IGNORECASE)
    return re.sub(
        r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*[^\s,;&]+",
        r"\1=[REDACTED]",
        value,
    )


class RedactingFormatter(logging.Formatter):
    """Keep accidental credentials out of all application log handlers."""

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        safe_record.msg = _redact(str(record.getMessage()))
        safe_record.args = ()
        return super().format(safe_record)


def setup_logging():
    """
    Configures application-wide structured logging.
    """
    logging_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter("%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"))
    logging.basicConfig(
        level=logging_level,
        handlers=[handler]
    )

logger = logging.getLogger("academic_ai_assistant")
