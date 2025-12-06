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

