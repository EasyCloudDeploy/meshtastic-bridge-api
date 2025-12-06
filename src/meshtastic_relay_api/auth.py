"""Authentication and authorization for Meshtastic Relay API."""

import logging
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery

from .config import Settings, get_logger

logger = get_logger(__name__)

# API Key header and query parameter
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="api_key", auto_error=False)


def get_api_key(
    header_key: Optional[str] = Security(API_KEY_HEADER),
    query_key: Optional[str] = Security(API_KEY_QUERY),
    settings: Settings = Depends(lambda: Settings()),
) -> str:
    """
    Validate API key from header or query parameter.

    Args:
        header_key: API key from X-API-Key header
        query_key: API key from api_key query parameter
        settings: Application settings

    Returns:
        Validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    # Check if authentication is enabled
    if not settings.enable_auth:
        logger.debug("Authentication is disabled")
        return "disabled"

    # Get API key from header or query parameter
    api_key = header_key or query_key

    if not api_key:
        logger.warning("API key missing from request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide X-API-Key header or api_key query parameter.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Validate API key
    if not settings.api_keys or api_key not in settings.api_keys:
        # Only log partial key in debug mode to reduce security risk
        if settings.sanitize_logs:
            logger.warning("Invalid API key attempted")
        else:
            logger.warning(f"Invalid API key attempted: {api_key[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    # Only log partial key in debug mode
    if not settings.sanitize_logs:
        logger.debug(f"API key validated successfully: {api_key[:8]}...")
    else:
        logger.debug("API key validated successfully")
    return api_key


def generate_api_key() -> str:
    """
    Generate a secure random API key.

    Returns:
        A secure random API key (32 bytes, hex encoded = 64 characters)
    """
    return secrets.token_urlsafe(32)


# Dependency for protected endpoints
RequireAuth = Depends(get_api_key)

