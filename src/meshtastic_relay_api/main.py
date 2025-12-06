"""Main FastAPI application for Meshtastic Relay API."""

import logging
from contextlib import asynccontextmanager

import re

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .auth import RequireAuth
from .config import Settings, get_logger
from .log_utils import sanitize_message
from .meshtastic_manager import MeshtasticManager
from .message_queue import MessageQueue
from .models import (
    ErrorResponse,
    HealthResponse,
    MessageResponse,
    QueueStatusResponse,
)
from .ollama_client import OllamaClient
from .rate_limit import get_rate_limit_key, get_rate_limiter
from .security_middleware import AuditLoggingMiddleware, SecurityHeadersMiddleware
from .version import get_version

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Configure audit logger
audit_logger = logging.getLogger("audit")
audit_handler = logging.StreamHandler()
audit_handler.setFormatter(
    logging.Formatter("%(asctime)s - AUDIT - %(levelname)s - %(message)s")
)
audit_logger.addHandler(audit_handler)
audit_logger.setLevel(logging.INFO)

logger = get_logger(__name__)

# Global instances
settings = Settings()
meshtastic_manager: MeshtasticManager | None = None
message_queue: MessageQueue | None = None
ollama_client: OllamaClient | None = None

# Initialize rate limiter early
limiter = get_rate_limiter(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan events.

    Args:
        app: FastAPI application instance
    """
    global meshtastic_manager, message_queue, ollama_client

    # Startup
    logger.info("Starting Meshtastic Relay API")
    logger.info(f"Connection type: {settings.connection_type.value}")
    
    # Log authentication status with appropriate warnings
    if settings.enable_auth:
        logger.info("Authentication: ENABLED")
        if not settings.api_keys or len(settings.api_keys) == 0:
            logger.warning(
                "⚠️  Authentication is enabled but no API keys configured. "
                "Set API_KEYS environment variable or set ENABLE_AUTH=false for trusted environments."
            )
        else:
            logger.info(f"API keys configured: {len(settings.api_keys)} key(s)")
    else:
        logger.warning(
            "⚠️  Authentication: DISABLED - API is open to all requests. "
            "Only use this in trusted environments (airgap networks, homelabs)."
        )
    
    logger.info(f"Rate limiting: {settings.rate_limit_per_minute} requests/minute")
    
    # Log debug mode status
    if settings.debug_mode:
        logger.warning(
            "⚠️  DEBUG MODE ENABLED - Messages will be logged but NOT sent to device"
        )
    else:
        logger.info("Debug mode: DISABLED (messages will be sent)")
    
    # Log blacklisted channels
    if settings.blacklisted_channels:
        logger.info(
            f"Blacklisted channels: {', '.join(settings.blacklisted_channels)} "
            f"({len(settings.blacklisted_channels)} channel(s))"
        )
    else:
        logger.info("No channels blacklisted")

    # Initialize and test Ollama connection
    if settings.ollama_server:
        logger.info(f"Initializing Ollama client (server: {settings.ollama_server}, model: {settings.ollama_model})")
        ollama_client = OllamaClient(settings)
        is_available, error_msg = ollama_client.test_connection()
        if is_available:
            logger.info(f"✓ Ollama connection successful (model: {settings.ollama_model})")
        else:
            logger.warning(f"⚠️  Ollama connection failed: {error_msg}")
            logger.warning("Message summarization will be disabled")
            ollama_client = None
    else:
        logger.info("Ollama not configured (OLLAMA_SERVER not set) - summarization disabled")

    # Validate settings
    is_valid, error_msg = settings.validate_connection_settings()
    if not is_valid:
        logger.error(f"Configuration error: {error_msg}")
        raise RuntimeError(f"Invalid configuration: {error_msg}")

    # Initialize Meshtastic manager
    meshtastic_manager = MeshtasticManager(settings)

    # Initialize message queue
    message_queue = MessageQueue(meshtastic_manager, settings)

    # Connect to Meshtastic device
    logger.info("Connecting to Meshtastic device...")
    if meshtastic_manager.connect():
        logger.info("Successfully connected to Meshtastic device")
    else:
        logger.warning("Failed to connect to Meshtastic device on startup, will retry on first message")

    # Start message queue processor
    message_queue.start()

    yield

    # Shutdown
    logger.info("Shutting down Meshtastic Relay API")
    if message_queue:
        message_queue.stop()
    if meshtastic_manager:
        meshtastic_manager.disconnect()


# Get application version
app_version = get_version()

# Create FastAPI app
app = FastAPI(
    title="Meshtastic Relay API",
    description="REST API to relay messages to Meshtastic devices via USB or TCP",
    version=app_version,
    lifespan=lifespan,
    docs_url="/docs" if not settings.enable_auth else None,  # Disable docs in production with auth
    redoc_url="/redoc" if not settings.enable_auth else None,
)

# Set rate limiter in app state
app.state.limiter = limiter

# Add security middleware
app.add_middleware(SecurityHeadersMiddleware, settings=settings)
app.add_middleware(AuditLoggingMiddleware)

# Configure CORS
if settings.enable_cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

# Add rate limit exception handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """
    Root endpoint.

    Returns:
        Welcome message
    """
    return {
        "service": "Meshtastic Relay API",
        "version": app_version,
        "status": "running",
    }


@app.get("/health", tags=["Health"], response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
        Health status information
    """
    if meshtastic_manager is None or message_queue is None:
        return HealthResponse(
            status="error",
            connected=False,
            connection_type=None,
            queue_size=0,
            version=app_version,
        )

    connection_info = meshtastic_manager.get_connection_info()
    queue_size = message_queue.get_queue_size()

    return HealthResponse(
        status="healthy" if connection_info.get("connected", False) else "degraded",
        connected=connection_info.get("connected", False),
        connection_type=connection_info.get("connection_type"),
        queue_size=queue_size,
        version=app_version,
    )


def validate_and_sanitize_channel(channel: str) -> str:
    """
    Validate and sanitize channel name.
    
    Args:
        channel: Channel name to validate
        
    Returns:
        Sanitized channel name
        
    Raises:
        ValueError: If channel is invalid
    """
    if not channel or not channel.strip():
        raise ValueError("Channel name is required and cannot be empty")
    # Remove potentially dangerous characters
    # Allow alphanumeric, spaces, hyphens, underscores only
    sanitized = re.sub(r"[^a-zA-Z0-9\s\-_]", "", channel)
    sanitized = sanitized.strip()
    if not sanitized:
        raise ValueError("Channel name is required and cannot be empty after sanitization")
    if len(sanitized) > 50:
        raise ValueError("Channel name exceeds maximum length of 50 characters")
    return sanitized


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.post(
    "/message",
    tags=["Messages"],
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def send_message(
    request: Request,
    channel: str = Query(..., description="Channel name (required)", min_length=1),
    force_summarize: bool = Query(
        False,
        description="Force summarization using Ollama. If true and summarization fails, an error is returned.",
    ),
) -> MessageResponse:
    """
    Send a message to the Meshtastic device.
    
    The request body is sent as the message text. The channel is specified
    as a query parameter.

    Args:
        request: FastAPI request object
        channel: Channel name (query parameter)
        force_summarize: If true, force summarization using Ollama. If summarization fails, an error is returned.

    Returns:
        Message response with queue information

    Raises:
        HTTPException: If message queue is not available, message is invalid, channel is missing, or summarization fails when forced
    """
    # Get client IP for audit logging
    client_ip = request.client.host if request.client else "unknown"
    if "x-forwarded-for" in request.headers:
        client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()

    if message_queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Message queue not initialized",
        )

    # Validate and sanitize channel
    try:
        sanitized_channel = validate_and_sanitize_channel(channel)
    except ValueError as e:
        audit_logger.warning(f"Message rejected from {client_ip}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Check if channel is blacklisted
    if settings.blacklisted_channels:
        channel_lower = sanitized_channel.lower()
        blacklisted_lower = [ch.lower() for ch in settings.blacklisted_channels]
        if channel_lower in blacklisted_lower:
            audit_logger.warning(
                f"Message rejected from {client_ip}: channel '{sanitized_channel}' is blacklisted"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Channel '{sanitized_channel}' is blacklisted and cannot be used",
            )

    # Read message from request body
    try:
        body_bytes = await request.body()
        message_text = body_bytes.decode("utf-8").strip()
    except Exception as e:
        logger.error(f"Error reading request body: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read message from request body",
        )

    # Validate message is not empty
    if not message_text:
        audit_logger.warning(f"Message rejected from {client_ip}: message body is empty")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message body cannot be empty",
        )

    # Handle summarization
    final_message = message_text
    was_summarized = False
    
    # Check if force_summarize is requested
    if force_summarize:
        if ollama_client is None:
            audit_logger.warning(
                f"Force summarize requested from {client_ip} but Ollama is not available"
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ollama is not configured or unavailable. Cannot force summarization.",
            )
        
        logger.info(f"Force summarization requested for {len(message_text)} character message")
        summary = ollama_client.summarize(message_text, force=True)
        
        if summary:
            final_message = summary
            was_summarized = True
            logger.info(f"Message summarized from {len(message_text)} to {len(summary)} characters")
            audit_logger.info(
                f"Message force-summarized: original={len(message_text)} chars, "
                f"summary={len(summary)} chars"
            )
        else:
            audit_logger.warning(
                f"Force summarization failed from {client_ip} for {len(message_text)} character message"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to summarize message. Ollama summarization returned no result.",
            )
    
    # Automatic summarization for messages 200+ characters (only if not force_summarize)
    elif len(message_text) >= 200 and ollama_client is not None:
        logger.info(f"Message is {len(message_text)} characters, attempting automatic summarization...")
        summary = ollama_client.summarize(message_text)
        if summary and len(summary) < len(message_text):
            final_message = summary
            was_summarized = True
            logger.info(f"Message summarized from {len(message_text)} to {len(summary)} characters")
            audit_logger.info(
                f"Message auto-summarized: original={len(message_text)} chars, "
                f"summary={len(summary)} chars"
            )
        else:
            logger.warning("Summarization failed or did not reduce message length, using original")

    # Validate final message length
    if len(final_message) > settings.max_message_length:
        audit_logger.warning(
            f"Message too long rejected from {client_ip}: "
            f"{len(final_message)} characters (was_summarized={was_summarized})"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Message exceeds maximum length of {settings.max_message_length} characters",
        )

    # Enqueue the message
    try:
        message_id, queue_position = message_queue.enqueue(
            message=final_message,
            channel=sanitized_channel,
        )

        # Audit log (sanitized)
        sanitized_msg = sanitize_message(final_message, settings)
        log_msg = (
            f"Message queued: ID={message_id[:8]}... "
            f"from {client_ip} "
            f"channel={sanitized_channel} "
            f"length={len(final_message)}"
        )
        if was_summarized:
            log_msg += f" (summarized from {len(message_text)} chars)"
        audit_logger.info(log_msg)

        return MessageResponse(
            success=True,
            message_id=message_id,
            message=final_message,
            channel=sanitized_channel,
            queue_position=queue_position,
        )

    except Exception as e:
        logger.error(f"Error enqueueing message: {e}", exc_info=True)
        audit_logger.error(f"Failed to queue message from {client_ip}: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue message",
        )


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.get(
    "/queue/status",
    tags=["Queue"],
    response_model=QueueStatusResponse,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def get_queue_status(request: Request) -> QueueStatusResponse:
    """
    Get current queue status.

    Returns:
        Queue status information

    Raises:
        HTTPException: If message queue is not available
    """
    if message_queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Message queue not initialized",
        )

    return QueueStatusResponse(
        queue_size=message_queue.get_queue_size(),
        processing=message_queue.is_processing(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
    """
    Custom HTTP exception handler.

    Args:
        request: Request object
        exc: HTTP exception

    Returns:
        JSON error response
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=exc.detail or "An error occurred", detail=None).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    General exception handler.

    Args:
        request: Request object
        exc: Exception

    Returns:
        JSON error response
    """
    # Log full error details server-side only
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    # Get client IP for audit logging
    client_ip = request.client.host if request.client else "unknown"
    audit_logger.error(f"Unhandled exception from {client_ip}: {type(exc).__name__}")

    # Never expose internal error details to clients
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            detail=None,  # Never expose internal details
        ).model_dump(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "meshtastic_relay_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        reload=False,
    )

