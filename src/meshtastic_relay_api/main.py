"""Main FastAPI application for Meshtastic Relay API."""

import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import re

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import uuid

from .auth import RequireAuth
from .config import Settings, get_logger
from .database import Database
from .log_utils import sanitize_message
from .meshtastic_manager import MeshtasticManager
from .message_queue import MessageQueue
from .models import (
    BatchMessageRequest,
    BatchMessageResponse,
    ErrorResponse,
    HealthResponse,
    MessageItem,
    MessageListResponse,
    MessageResponse,
    MessageStatusResponse,
    QueueStatusResponse,
    ScheduledMessageRequest,
    ScheduledMessageResponse,
    WebhookRequest,
    WebhookResponse,
)
from .ollama_client import OllamaClient
from .rate_limit import get_rate_limit_key, get_rate_limiter
from .scheduler import MessageScheduler
from .security_middleware import AuditLoggingMiddleware, SecurityHeadersMiddleware
from .version import get_version
from .webhook_handler import WebhookHandler

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
database: Database | None = None
webhook_handler: WebhookHandler | None = None
scheduler: MessageScheduler | None = None

# Initialize rate limiter early
limiter = get_rate_limiter(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan events.

    Args:
        app: FastAPI application instance
    """
    global meshtastic_manager, message_queue, ollama_client, database, webhook_handler, scheduler

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

    # Initialize database
    logger.info("Initializing database...")
    database = Database(settings, settings.db_path)
    logger.info("Database initialized")

    # Define message callback for incoming messages
    def on_message_received(
        message_text: str, channel: str, sender_id: str | None, sender_name: str | None
    ) -> None:
        """Callback for handling incoming messages."""
        message_id = str(uuid.uuid4())
        try:
            # Save to database
            database.save_message(
                message_id=message_id,
                message_text=message_text,
                channel=channel,
                direction="received",
                sender_id=sender_id,
                sender_name=sender_name,
                status="received",
                received_at=time.time(),
            )
            # Deliver to webhooks
            if webhook_handler:
                webhook_handler.deliver_message(
                    message_text=message_text,
                    channel=channel,
                    sender_id=sender_id,
                    sender_name=sender_name,
                )
        except Exception as e:
            logger.error(f"Error handling received message: {e}", exc_info=True)

    # Initialize Meshtastic manager with message callback
    meshtastic_manager = MeshtasticManager(settings, message_callback=on_message_received)

    # Define status callback for message queue
    def on_message_status(message_id: str, status: str, sent_at: float | None) -> None:
        """Callback for message status updates."""
        if database:
            try:
                database.update_message_status(message_id, status, sent_at)
            except Exception as e:
                logger.warning(f"Error updating message status in database: {e}")

    # Initialize message queue with status callback
    message_queue = MessageQueue(meshtastic_manager, settings, status_callback=on_message_status)

    # Initialize webhook handler
    webhook_handler = WebhookHandler(database, settings)

    # Initialize scheduler
    scheduler = MessageScheduler(database, message_queue, meshtastic_manager, settings)

    # Connect to Meshtastic device
    logger.info("Connecting to Meshtastic device...")
    if meshtastic_manager.connect():
        logger.info("Successfully connected to Meshtastic device")
    else:
        logger.warning("Failed to connect to Meshtastic device on startup, will retry on first message")

    # Start message queue processor
    message_queue.start()

    # Start scheduler
    scheduler.start()

    yield

    # Shutdown
    logger.info("Shutting down Meshtastic Relay API")
    if scheduler:
        scheduler.stop()
    if message_queue:
        message_queue.stop()
    if meshtastic_manager:
        meshtastic_manager.disconnect()


# Get application version
app_version = get_version()

# Create FastAPI app with comprehensive OpenAPI documentation
app = FastAPI(
    title="Meshtastic Relay API",
    description="""
## Meshtastic Relay API

A comprehensive REST API for bidirectional communication with Meshtastic mesh network devices.

### Features

- **Bidirectional Messaging**: Send and receive messages via Meshtastic devices
- **Message History**: SQLite database stores all sent and received messages
- **Webhook Support**: Real-time webhook notifications for incoming messages
- **Scheduled Messages**: Schedule messages to be sent at specific times
- **Batch Operations**: Send multiple messages efficiently in a single request
- **Message Summarization**: Automatic message summarization using Ollama (optional)
- **Channel Management**: Support for multiple channels with filtering
- **Message Status Tracking**: Track message delivery status (queued, sent, failed)
- **Rate Limiting**: Configurable rate limiting per IP/API key
- **Authentication**: Optional API key authentication for production use

### Connection Types

- **USB**: Direct connection via USB serial port
- **TCP**: Network connection via TCP/IP

### Authentication

When `ENABLE_AUTH=true`, provide your API key using one of these methods:

1. **Header**: `X-API-Key: your-api-key-here`
2. **Query Parameter**: `?api_key=your-api-key-here`

### Rate Limiting

All endpoints are rate-limited. Default: 60 requests per minute per IP/API key.

### Message Limits

- Maximum message length: 200 characters (Meshtastic limit)
- Messages exceeding 200 characters are automatically summarized if Ollama is configured
- Use `force_summarize=true` query parameter to force summarization

### Webhooks

Configure webhooks to receive real-time notifications when messages are received:
- Per-channel filtering
- Optional authentication secrets
- Automatic retry on failure

### Examples

See individual endpoint documentation for request/response examples.
    """,
    version=app_version,
    lifespan=lifespan,
    docs_url="/docs" if not settings.enable_auth else None,
    redoc_url="/redoc" if not settings.enable_auth else None,
    openapi_tags=[
        {
            "name": "Root",
            "description": "Root endpoint and service information",
        },
        {
            "name": "Health",
            "description": "Health check and service status endpoints",
        },
        {
            "name": "Messages",
            "description": "Send, receive, and manage messages. Includes scheduling, batch operations, and message history.",
        },
        {
            "name": "Queue",
            "description": "Message queue status and monitoring",
        },
        {
            "name": "Webhooks",
            "description": "Configure webhooks for real-time message notifications",
        },
    ],
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
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

# Add rate limit exception handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get(
    "/openapi.json",
    tags=["Root"],
    summary="OpenAPI Specification (JSON)",
    description="Get the OpenAPI specification in JSON format.",
    include_in_schema=False,
)
async def get_openapi_json() -> dict:
    """Return OpenAPI specification in JSON format."""
    return app.openapi()


@app.get(
    "/openapi.yaml",
    tags=["Root"],
    summary="OpenAPI Specification (YAML)",
    description="Get the OpenAPI specification in YAML format.",
    response_class=Response,
    include_in_schema=False,
)
async def get_openapi_yaml() -> Response:
    """Return OpenAPI specification in YAML format."""
    try:
        import yaml

        openapi_schema = app.openapi()
        yaml_content = yaml.dump(
            openapi_schema, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
        return Response(content=yaml_content, media_type="application/x-yaml")
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="YAML export not available. Install pyyaml to enable.",
        )


@app.get(
    "/",
    tags=["Root"],
    summary="Service Information",
    description="Get basic information about the API service including version and status.",
    response_description="Service information",
    responses={
        200: {
            "description": "Service information",
            "content": {
                "application/json": {
                    "example": {
                        "service": "Meshtastic Relay API",
                        "version": "1.0.0",
                        "status": "running",
                    }
                }
            },
        }
    },
)
async def root() -> dict[str, str]:
    """
    Root endpoint providing service information.

    Returns basic information about the API including:
    - Service name
    - API version
    - Current status

    **Example Response:**
    ```json
    {
        "service": "Meshtastic Relay API",
        "version": "1.0.0",
        "status": "running"
    }
    ```
    """
    return {
        "service": "Meshtastic Relay API",
        "version": app_version,
        "status": "running",
    }


@app.get(
    "/health",
    tags=["Health"],
    response_model=HealthResponse,
    summary="Health Check",
    description="Check the health status of the API service and Meshtastic device connection.",
    response_description="Health status information",
    responses={
        200: {
            "description": "Health status",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "connected": True,
                        "connection_type": "tcp",
                        "queue_size": 0,
                        "version": "1.0.0",
                    }
                }
            },
        }
    },
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns comprehensive health information including:
    - Service status (healthy/degraded/error)
    - Meshtastic device connection status
    - Connection type (USB/TCP)
    - Current message queue size
    - API version

    **Status Values:**
    - `healthy`: Service is running and device is connected
    - `degraded`: Service is running but device is not connected
    - `error`: Service is not properly initialized

    **Example Response:**
    ```json
    {
        "status": "healthy",
        "connected": true,
        "connection_type": "tcp",
        "queue_size": 0,
        "version": "1.0.0"
    }
    ```
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
    summary="Send Message",
    description="""
    Send a message to the Meshtastic device via the specified channel.
    
    The message text is sent in the request body, and the channel is specified as a query parameter.
    Messages are queued and processed asynchronously.
    
    **Message Processing:**
    - Messages are automatically summarized if they exceed 200 characters (if Ollama is configured)
    - Use `force_summarize=true` to force summarization even for shorter messages
    - Messages are validated and stored in the database
    - Returns immediately with message ID and queue position
    
    **Channel Requirements:**
    - Channel name must match exactly (case-sensitive) as configured on the device
    - Channel names are sanitized (alphanumeric, spaces, hyphens, underscores only)
    - Blacklisted channels will be rejected with 403 Forbidden
    """,
    response_description="Message queued successfully",
    responses={
        202: {
            "description": "Message queued successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message_id": "550e8400-e29b-41d4-a716-446655440000",
                        "message": "Hello from the API!",
                        "channel": "LongFast",
                        "queue_position": 1,
                    }
                }
            },
        },
        400: {"description": "Invalid request (empty message, invalid channel, message too long)"},
        403: {"description": "Channel is blacklisted"},
        503: {"description": "Service unavailable (Ollama not available when force_summarize=true)"},
    },
)
async def send_message(
    request: Request,
    channel: str = Query(
        ...,
        description="Channel name (required). Must match exactly as configured on the device (case-sensitive).",
        min_length=1,
        example="LongFast",
    ),
    force_summarize: bool = Query(
        False,
        description="Force summarization using Ollama. If true and Ollama is unavailable, returns 503 error.",
        example=False,
    ),
) -> MessageResponse:
    """
    Send a message to the Meshtastic device.
    
    **Request Format:**
    - Method: `POST`
    - URL: `/message?channel=LongFast&force_summarize=false`
    - Body: Plain text message (UTF-8)
    - Content-Type: `text/plain` or `application/octet-stream`
    
    **Example Request:**
    ```bash
    curl -X POST "http://localhost:8000/message?channel=LongFast" \\
      -H "X-API-Key: your-api-key" \\
      -H "Content-Type: text/plain" \\
      -d "Hello from the API!"
    ```
    
    **Example Response:**
    ```json
    {
        "success": true,
        "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "message": "Hello from the API!",
        "channel": "LongFast",
        "queue_position": 1
    }
    ```
    
    **Notes:**
    - Maximum message length: 200 characters (Meshtastic limit)
    - Messages longer than 200 characters are automatically summarized if Ollama is configured
    - Channel names are case-sensitive and must match device configuration exactly
    - Messages are processed asynchronously - check status via `/messages/{message_id}/status`
    """
    # Get client IP for audit logging (validate X-Forwarded-For to prevent spoofing)
    client_ip = request.client.host if request.client else "unknown"
    # Only trust X-Forwarded-For if we're behind a reverse proxy (in production)
    # For now, prefer direct client IP but log X-Forwarded-For if present
    if "x-forwarded-for" in request.headers:
        forwarded_ips = [ip.strip() for ip in request.headers["x-forwarded-for"].split(",")]
        # Use first IP but log warning if multiple (potential spoofing)
        if len(forwarded_ips) > 1:
            logger.debug(f"Multiple X-Forwarded-For values detected: {forwarded_ips}")
        # Sanitize IP to prevent injection
        forwarded_ip = forwarded_ips[0] if forwarded_ips else client_ip
        # Basic validation: should be valid IP format
        if forwarded_ip and not forwarded_ip.startswith("unknown"):
            client_ip = forwarded_ip

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
    # Support both JSON and plain text payloads
    try:
        content_type = request.headers.get("content-type", "").lower()
        body_bytes = await request.body()
        
        # Handle JSON payloads (e.g., from webhooks like Plex)
        if "application/json" in content_type:
            try:
                body_json = json.loads(body_bytes.decode("utf-8"))
                # Try common JSON fields for message content
                if isinstance(body_json, dict):
                    # Common webhook fields - try in order of preference
                    message_text = (
                        body_json.get("message") or
                        body_json.get("text") or
                        body_json.get("content") or
                        body_json.get("body") or
                        body_json.get("payload", {}).get("message") or
                        body_json.get("event", {}).get("message")
                    )
                    # If no standard field found, try to extract meaningful text from the JSON
                    if message_text is None:
                        # Fallback: look for any string value in the top level
                        for key, value in body_json.items():
                            if isinstance(value, str) and value.strip():
                                message_text = value
                                break
                        # Last resort: convert entire JSON to string (but format it nicely)
                        if message_text is None:
                            message_text = json.dumps(body_json, indent=2)
                else:
                    # If JSON is not a dict, convert to string
                    message_text = str(body_json)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in request body: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid JSON in request body",
                )
        else:
            # Handle plain text payloads (default behavior)
            # Try UTF-8 first, fall back to other encodings if needed
            try:
                message_text = body_bytes.decode("utf-8").strip()
            except UnicodeDecodeError:
                # Try other common encodings
                for encoding in ["latin-1", "iso-8859-1", "cp1252"]:
                    try:
                        message_text = body_bytes.decode(encoding).strip()
                        logger.warning(f"Decoded request body using {encoding} encoding instead of UTF-8")
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    # If all encodings fail, raise error
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Request body contains invalid characters and cannot be decoded",
                    )
        
        # Ensure we have a string
        if not isinstance(message_text, str):
            message_text = str(message_text)
        message_text = message_text.strip()
        
    except HTTPException:
        raise
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

        # Save to database
        if database:
            try:
                database.save_message(
                    message_id=message_id,
                    message_text=final_message,
                    channel=sanitized_channel,
                    direction="sent",
                    status="queued",
                )
            except Exception as e:
                logger.warning(f"Failed to save message to database: {e}")

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


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.get(
    "/messages",
    tags=["Messages"],
    response_model=MessageListResponse,
    dependencies=[RequireAuth] if settings.enable_auth else [],
    summary="List Messages",
    description="""
    Retrieve a paginated list of messages from the database.
    
    Supports filtering by channel and direction (sent/received).
    Messages are returned in reverse chronological order (newest first).
    """,
    response_description="Paginated list of messages",
    responses={
        200: {
            "description": "List of messages",
            "content": {
                "application/json": {
                    "example": {
                        "messages": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "message_text": "Hello from the API!",
                                "channel": "LongFast",
                                "direction": "sent",
                                "sender_id": None,
                                "sender_name": None,
                                "status": "sent",
                                "created_at": 1699123456.789,
                                "sent_at": 1699123457.123,
                                "received_at": None,
                            }
                        ],
                        "total": 1,
                        "limit": 100,
                        "offset": 0,
                    }
                }
            },
        },
        503: {"description": "Database not initialized"},
    },
)
async def get_messages(
    request: Request,
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Maximum number of messages to return (1-1000)",
        example=100,
    ),
    offset: int = Query(0, ge=0, description="Offset for pagination", example=0),
    channel: Optional[str] = Query(
        None, description="Filter by channel name (exact match)", example="LongFast"
    ),
    direction: Optional[str] = Query(
        None,
        description="Filter by direction: 'sent' or 'received'",
        example="sent",
    ),
) -> MessageListResponse:
    """
    Get list of messages with optional filtering.

    **Query Parameters:**
    - `limit`: Number of messages to return (default: 100, max: 1000)
    - `offset`: Pagination offset (default: 0)
    - `channel`: Filter by channel name (optional, exact match)
    - `direction`: Filter by direction - 'sent' or 'received' (optional, must be exactly 'sent' or 'received')

    **Example Request:**
    ```bash
    curl "http://localhost:8000/messages?limit=50&offset=0&channel=LongFast&direction=sent" \\
      -H "X-API-Key: your-api-key"
    ```

    **Example Response:**
    ```json
    {
        "messages": [
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "message_text": "Hello from the API!",
                "channel": "LongFast",
                "direction": "sent",
                "status": "sent",
                "created_at": 1699123456.789,
                "sent_at": 1699123457.123
            }
        ],
        "total": 1,
        "limit": 100,
        "offset": 0
    }
    ```
    """
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    # Validate direction parameter
    if direction is not None and direction not in ("sent", "received"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Direction must be either 'sent' or 'received'",
        )

    messages = database.get_messages(
        limit=limit, offset=offset, channel=channel, direction=direction
    )
    # Use efficient count query instead of fetching all messages
    total = database.count_messages(channel=channel, direction=direction)

    return MessageListResponse(
        messages=[MessageItem(**msg) for msg in messages],
        total=total,
        limit=limit,
        offset=offset,
    )


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.get(
    "/messages/{message_id}",
    tags=["Messages"],
    response_model=MessageItem,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def get_message(
    request: Request, message_id: str
) -> MessageItem:
    """
    Get a single message by ID.

    Args:
        message_id: Message identifier

    Returns:
        Message details
    """
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    message = database.get_message(message_id)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    return MessageItem(**message)


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.get(
    "/messages/{message_id}/status",
    tags=["Messages"],
    response_model=MessageStatusResponse,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def get_message_status(
    request: Request, message_id: str
) -> MessageStatusResponse:
    """
    Get message status.

    Args:
        message_id: Message identifier

    Returns:
        Message status information
    """
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    message = database.get_message(message_id)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    return MessageStatusResponse(
        message_id=message["id"],
        status=message["status"],
        created_at=message["created_at"],
        sent_at=message.get("sent_at"),
        received_at=message.get("received_at"),
    )


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.post(
    "/messages/schedule",
    tags=["Messages"],
    response_model=ScheduledMessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def schedule_message(
    request: Request, scheduled_request: ScheduledMessageRequest
) -> ScheduledMessageResponse:
    """
    Schedule a message to be sent at a specific time.

    Args:
        scheduled_request: Scheduled message request

    Returns:
        Scheduled message response
    """
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    # Validate scheduled time is in the future
    current_time = time.time()
    if scheduled_request.scheduled_at <= current_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scheduled time must be in the future",
        )

    # Validate channel
    try:
        sanitized_channel = validate_and_sanitize_channel(scheduled_request.channel)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Validate message length
    if len(scheduled_request.message) > settings.max_message_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Message exceeds maximum length of {settings.max_message_length} characters",
        )

    message_id = str(uuid.uuid4())
    database.save_scheduled_message(
        message_id=message_id,
        message_text=scheduled_request.message,
        channel=sanitized_channel,
        scheduled_at=scheduled_request.scheduled_at,
        recurrence_pattern=scheduled_request.recurrence_pattern,
    )

    return ScheduledMessageResponse(
        success=True,
        message_id=message_id,
        scheduled_at=scheduled_request.scheduled_at,
    )


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.post(
    "/messages/batch",
    tags=["Messages"],
    response_model=BatchMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def send_batch_messages(
    request: Request, batch_request: BatchMessageRequest
) -> BatchMessageResponse:
    """
    Send multiple messages in a batch.

    Args:
        batch_request: Batch message request

    Returns:
        Batch message response with results
    """
    if message_queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Message queue not initialized",
        )

    results = []
    queued = 0
    failed = 0

    for msg in batch_request.messages:
        try:
            message_text = msg.get("message", "")
            channel = msg.get("channel", "")

            if not message_text or not channel:
                results.append(
                    {
                        "success": False,
                        "error": "Message and channel are required",
                        "message": message_text[:50] if message_text else "",
                    }
                )
                failed += 1
                continue

            # Validate channel
            try:
                sanitized_channel = validate_and_sanitize_channel(channel)
            except ValueError as e:
                results.append(
                    {
                        "success": False,
                        "error": str(e),
                        "message": message_text[:50],
                    }
                )
                failed += 1
                continue

            # Validate message length
            if len(message_text) > settings.max_message_length:
                results.append(
                    {
                        "success": False,
                        "error": f"Message exceeds maximum length of {settings.max_message_length} characters",
                        "message": message_text[:50],
                    }
                )
                failed += 1
                continue

            # Enqueue message
            message_id, queue_position = message_queue.enqueue(
                message=message_text,
                channel=sanitized_channel,
            )

            # Save to database
            if database:
                try:
                    database.save_message(
                        message_id=message_id,
                        message_text=message_text,
                        channel=sanitized_channel,
                        direction="sent",
                        status="queued",
                    )
                except Exception as e:
                    logger.warning(f"Failed to save batch message to database: {e}")

            results.append(
                {
                    "success": True,
                    "message_id": message_id,
                    "channel": sanitized_channel,
                    "queue_position": queue_position,
                }
            )
            queued += 1

        except Exception as e:
            logger.error(f"Error processing batch message: {e}", exc_info=True)
            results.append(
                {
                    "success": False,
                    "error": "Internal error processing message",
                    "message": msg.get("message", "")[:50],
                }
            )
            failed += 1

    return BatchMessageResponse(
        success=True,
        total=len(batch_request.messages),
        queued=queued,
        failed=failed,
        results=results,
    )


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.post(
    "/webhooks",
    tags=["Webhooks"],
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def create_webhook(request: Request, webhook_request: WebhookRequest) -> WebhookResponse:
    """
    Create a webhook configuration.

    Args:
        webhook_request: Webhook configuration

    Returns:
        Created webhook response
    """
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    # Validate webhook URL to prevent SSRF attacks
    is_valid, error_msg = WebhookHandler.validate_webhook_url(webhook_request.url)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid webhook URL: {error_msg}",
        )

    webhook_id = str(uuid.uuid4())
    database.add_webhook(
        webhook_id=webhook_id,
        url=webhook_request.url,
        channel_filter=webhook_request.channel_filter,
        secret=webhook_request.secret,
    )

    webhooks = database.get_webhooks()
    created_webhook = next((w for w in webhooks if w["id"] == webhook_id), None)

    if not created_webhook:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve created webhook",
        )

    return WebhookResponse(
        id=created_webhook["id"],
        url=created_webhook["url"],
        channel_filter=created_webhook.get("channel_filter"),
        enabled=bool(created_webhook.get("enabled", 1)),
        created_at=created_webhook["created_at"],
    )


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.get(
    "/webhooks",
    tags=["Webhooks"],
    response_model=list[WebhookResponse],
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def list_webhooks(request: Request) -> list[WebhookResponse]:
    """
    List all webhook configurations.

    Returns:
        List of webhooks
    """
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    webhooks = database.get_webhooks(enabled_only=False)
    return [
        WebhookResponse(
            id=w["id"],
            url=w["url"],
            channel_filter=w.get("channel_filter"),
            enabled=bool(w.get("enabled", 1)),
            created_at=w["created_at"],
        )
        for w in webhooks
    ]


@limiter.limit(f"{settings.rate_limit_per_minute}/minute", key_func=get_rate_limit_key)
@app.delete(
    "/webhooks/{webhook_id}",
    tags=["Webhooks"],
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[RequireAuth] if settings.enable_auth else [],
)
async def delete_webhook(request: Request, webhook_id: str) -> None:
    """
    Delete a webhook configuration.

    Args:
        webhook_id: Webhook identifier
    """
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized",
        )

    database.delete_webhook(webhook_id)


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

