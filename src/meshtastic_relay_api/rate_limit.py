"""Rate limiting for Meshtastic Relay API."""

import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import Request, status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import Settings, get_logger

logger = get_logger(__name__)

# Global rate limiter instance
limiter: Optional[Limiter] = None


def get_rate_limiter(settings: Settings) -> Limiter:
    """
    Initialize and return rate limiter instance.

    Args:
        settings: Application settings

    Returns:
        Configured rate limiter instance
    """
    global limiter
    if limiter is None:
        # Use in-memory storage (for single-instance deployments)
        # For multi-instance, consider Redis backend
        limiter = Limiter(
            key_func=get_remote_address,
            default_limits=[f"{settings.rate_limit_per_minute}/minute"],
            storage_uri="memory://",
        )
    return limiter


def get_rate_limit_key(request: Request) -> str:
    """
    Get rate limit key for request.

    Args:
        request: FastAPI request object

    Returns:
        Rate limit key (IP address or API key if available)
    """
    # Try to get API key from header or query
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if api_key:
        # Rate limit by API key for authenticated requests
        return f"api_key:{api_key}"
    # Fall back to IP address
    return get_remote_address(request)


def create_rate_limit_exceeded_handler(settings: Settings):
    """
    Create custom rate limit exceeded handler.

    Args:
        settings: Application settings

    Returns:
        Handler function
    """

    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        """Custom handler for rate limit exceeded."""
        logger.warning(
            f"Rate limit exceeded for {get_rate_limit_key(request)}: {exc.detail}"
        )
        return _rate_limit_exceeded_handler(request, exc)

    return rate_limit_handler

