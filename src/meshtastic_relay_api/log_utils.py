"""Logging utilities with sanitization support."""

import logging
import re
from typing import Any

from .config import Settings


def sanitize_message(message: str, settings: Settings) -> str:
    """
    Sanitize message content for logging.

    Args:
        message: Message content to sanitize
        settings: Application settings

    Returns:
        Sanitized message (truncated or redacted)
    """
    if not settings.sanitize_logs:
        return message

    # Truncate long messages
    if len(message) > 50:
        return f"{message[:50]}... (truncated)"
    return message


def sanitize_api_key(api_key: str | None, settings: Settings) -> str:
    """
    Sanitize API key for logging.

    Args:
        api_key: API key to sanitize
        settings: Application settings

    Returns:
        Sanitized API key (first 8 chars only)
    """
    if not api_key:
        return "none"
    if not settings.sanitize_logs:
        return api_key
    return f"{api_key[:8]}..." if len(api_key) > 8 else "***"


def sanitize_channel(channel: str | None) -> str:
    """
    Sanitize channel name (validate against injection patterns).

    Args:
        channel: Channel name to sanitize

    Returns:
        Sanitized channel name
    """
    if not channel:
        return "default"
    # Remove any potentially dangerous characters
    # Allow alphanumeric, spaces, hyphens, underscores
    sanitized = re.sub(r"[^a-zA-Z0-9\s\-_]", "", channel)
    return sanitized.strip()

