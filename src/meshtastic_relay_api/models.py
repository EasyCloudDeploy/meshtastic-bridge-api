"""Pydantic models for API request/response validation."""

from typing import Optional

import re

from pydantic import BaseModel, Field, field_validator


class MessageRequest(BaseModel):
    """Request model for sending a message."""

    message: str = Field(
        ...,
        description="Message text to send",
        min_length=1,
        max_length=200,
    )
    channel: str = Field(
        ...,
        description="Channel name (required)",
        min_length=1,
        max_length=50,
    )

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        """Validate and sanitize channel name."""
        if not v or not v.strip():
            raise ValueError("Channel name is required and cannot be empty")
        # Remove potentially dangerous characters
        # Allow alphanumeric, spaces, hyphens, underscores only
        sanitized = re.sub(r"[^a-zA-Z0-9\s\-_]", "", v)
        sanitized = sanitized.strip()
        if not sanitized:
            raise ValueError("Channel name is required and cannot be empty after sanitization")
        if len(sanitized) > 50:
            raise ValueError("Channel name exceeds maximum length of 50 characters")
        return sanitized

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Validate message content."""
        if not v or not v.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return v.strip()


class MessageResponse(BaseModel):
    """Response model for message sending operations."""

    success: bool = Field(..., description="Whether the message was queued successfully")
    message_id: str = Field(..., description="Unique identifier for the queued message")
    message: str = Field(..., description="The message that was queued")
    channel: str = Field(..., description="Channel the message will be sent to")
    queue_position: Optional[int] = Field(
        default=None,
        description="Position in the queue (if available)",
    )


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Additional error details")


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Service status")
    connected: bool = Field(..., description="Whether connected to Meshtastic device")
    connection_type: Optional[str] = Field(
        default=None,
        description="Type of connection (usb/tcp)",
    )
    queue_size: int = Field(..., description="Current message queue size")
    version: str = Field(..., description="Application version")


class QueueStatusResponse(BaseModel):
    """Queue status response model."""

    queue_size: int = Field(..., description="Current number of messages in queue")
    processing: bool = Field(..., description="Whether queue processor is running")


class MessageItem(BaseModel):
    """Individual message item in list response."""

    id: str = Field(..., description="Message identifier")
    message_text: str = Field(..., description="Message content")
    channel: str = Field(..., description="Channel name")
    direction: str = Field(..., description="Message direction: 'sent' or 'received'")
    sender_id: Optional[str] = Field(default=None, description="Sender node ID")
    sender_name: Optional[str] = Field(default=None, description="Sender name")
    status: str = Field(..., description="Message status")
    created_at: float = Field(..., description="Timestamp when message was created")
    sent_at: Optional[float] = Field(default=None, description="Timestamp when message was sent")
    received_at: Optional[float] = Field(
        default=None, description="Timestamp when message was received"
    )


class MessageListResponse(BaseModel):
    """Response model for message list."""

    messages: list[MessageItem] = Field(..., description="List of messages")
    total: int = Field(..., description="Total number of messages")
    limit: int = Field(..., description="Limit used in query")
    offset: int = Field(..., description="Offset used in query")


class ScheduledMessageRequest(BaseModel):
    """Request model for scheduling a message."""

    message: str = Field(..., description="Message text to send", min_length=1)
    channel: str = Field(..., description="Channel name (required)", min_length=1)
    scheduled_at: float = Field(..., description="Unix timestamp when message should be sent")
    recurrence_pattern: Optional[str] = Field(
        default=None, description="Optional cron-like recurrence pattern"
    )


class ScheduledMessageResponse(BaseModel):
    """Response model for scheduled message operations."""

    success: bool = Field(..., description="Whether the message was scheduled successfully")
    message_id: str = Field(..., description="Unique identifier for the scheduled message")
    scheduled_at: float = Field(..., description="Timestamp when message will be sent")


class BatchMessageRequest(BaseModel):
    """Request model for batch message sending."""

    messages: list[dict] = Field(
        ...,
        description="List of messages, each with 'message' and 'channel' fields",
        min_length=1,
    )


class BatchMessageResponse(BaseModel):
    """Response model for batch message operations."""

    success: bool = Field(..., description="Whether batch was queued successfully")
    total: int = Field(..., description="Total number of messages in batch")
    queued: int = Field(..., description="Number of messages successfully queued")
    failed: int = Field(..., description="Number of messages that failed")
    results: list[dict] = Field(..., description="Individual message results")


class WebhookRequest(BaseModel):
    """Request model for creating a webhook."""

    url: str = Field(..., description="Webhook URL", min_length=1)
    channel_filter: Optional[str] = Field(
        default=None, description="Optional channel name filter"
    )
    secret: Optional[str] = Field(default=None, description="Optional secret for authentication")


class WebhookResponse(BaseModel):
    """Response model for webhook operations."""

    id: str = Field(..., description="Webhook identifier")
    url: str = Field(..., description="Webhook URL")
    channel_filter: Optional[str] = Field(default=None, description="Channel filter")
    enabled: bool = Field(..., description="Whether webhook is enabled")
    created_at: float = Field(..., description="Timestamp when webhook was created")


class MessageStatusResponse(BaseModel):
    """Response model for message status."""

    message_id: str = Field(..., description="Message identifier")
    status: str = Field(..., description="Current status")
    created_at: float = Field(..., description="Timestamp when message was created")
    sent_at: Optional[float] = Field(default=None, description="Timestamp when message was sent")
    received_at: Optional[float] = Field(
        default=None, description="Timestamp when message was received"
    )

