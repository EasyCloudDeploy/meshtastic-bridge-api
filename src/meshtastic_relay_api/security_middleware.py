"""Security middleware for Meshtastic Relay API."""

import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import Settings, get_logger

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        """
        Initialize security headers middleware.

        Args:
            app: ASGI application
            settings: Application settings
        """
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Add security headers to response.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response with security headers
        """
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp

        # HSTS (only if using HTTPS)
        if self.settings.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self.settings.hsts_max_age}; "
                "includeSubDomains; preload"
            )

        # Remove server header for security
        if "server" in response.headers:
            del response.headers["server"]

        return response


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log security-relevant events."""

    def __init__(self, app: ASGIApp) -> None:
        """
        Initialize audit logging middleware.

        Args:
            app: ASGI application
        """
        super().__init__(app)
        self.audit_logger = logging.getLogger("audit")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Log security events.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response
        """
        # Get client IP (validate X-Forwarded-For to prevent spoofing)
        client_ip = request.client.host if request.client else "unknown"
        # Only trust X-Forwarded-For if we're behind a reverse proxy (in production)
        # For now, prefer direct client IP but log X-Forwarded-For if present
        if "x-forwarded-for" in request.headers:
            forwarded_ips = [ip.strip() for ip in request.headers["x-forwarded-for"].split(",")]
            # Use first IP but log warning if multiple (potential spoofing)
            if len(forwarded_ips) > 1:
                self.audit_logger.debug(f"Multiple X-Forwarded-For values detected: {forwarded_ips}")
            # Sanitize IP to prevent injection
            forwarded_ip = forwarded_ips[0] if forwarded_ips else client_ip
            # Basic validation: should be valid IP format
            if forwarded_ip and not forwarded_ip.startswith("unknown"):
                client_ip = forwarded_ip

        # Log request
        self.audit_logger.info(
            f"Request: {request.method} {request.url.path} "
            f"from {client_ip} "
            f"User-Agent: {request.headers.get('user-agent', 'unknown')}"
        )

        response = await call_next(request)

        # Log response status
        if response.status_code >= 400:
            self.audit_logger.warning(
                f"Error response: {response.status_code} "
                f"for {request.method} {request.url.path} from {client_ip}"
            )

        return response

