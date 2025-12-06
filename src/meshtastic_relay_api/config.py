"""Configuration management for Meshtastic Relay API."""

import logging
from enum import Enum
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConnectionType(str, Enum):
    """Supported connection types for Meshtastic devices."""

    USB = "usb"
    TCP = "tcp"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Connection settings
    connection_type: ConnectionType = Field(
        default=ConnectionType.TCP,
        description="Connection type: 'usb' or 'tcp'",
    )
    usb_device: Optional[str] = Field(
        default=None,
        description="USB device path (e.g., /dev/ttyUSB0 or COM3)",
    )
    tcp_host: Optional[str] = Field(
        default=None,
        description="TCP hostname or IP address (port is handled by Meshtastic library)",
    )

    # API settings
    api_host: str = Field(
        default="0.0.0.0",
        description="API server host",
    )
    api_port: int = Field(
        default=8000,
        description="API server port",
        ge=1,
        le=65535,
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )

    # Message settings
    max_message_length: int = Field(
        default=200,
        description="Maximum message length in characters",
        ge=1,
        le=200,
    )
    blacklisted_channels: Optional[list[str]] = Field(
        default=None,
        description="List of blacklisted channel names (comma-separated in env var)",
    )

    # Security settings
    enable_auth: bool = Field(
        default=False,
        description="Enable API key authentication (set to true for production/untrusted networks)",
    )
    api_keys: Optional[list[str]] = Field(
        default=None,
        description="List of valid API keys (comma-separated in env var)",
    )
    rate_limit_per_minute: int = Field(
        default=60,
        description="Rate limit per minute per IP/API key",
        ge=1,
    )
    enable_cors: bool = Field(
        default=True,
        description="Enable CORS",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins (comma-separated in env var). Default: empty (no CORS). Use '*' for all origins.",
    )
    enable_hsts: bool = Field(
        default=False,
        description="Enable HSTS header (only use with HTTPS)",
    )
    hsts_max_age: int = Field(
        default=31536000,
        description="HSTS max-age in seconds (default: 1 year)",
        ge=0,
    )
    sanitize_logs: bool = Field(
        default=True,
        description="Sanitize sensitive data from logs",
    )
    debug_mode: bool = Field(
        default=False,
        description="Enable debug/dry-run mode - logs message details without actually sending",
    )

    # Ollama settings
    ollama_server: Optional[str] = Field(
        default=None,
        description="Ollama server URL (e.g., http://localhost:11434). If not set, summarization is disabled.",
    )
    ollama_model: Optional[str] = Field(
        default="llama3.2",
        description="Ollama model name to use for summarization",
    )
    ollama_timeout: int = Field(
        default=30,
        description="Timeout in seconds for Ollama API requests",
        ge=1,
        le=300,
    )

    # Database settings
    db_path: Optional[str] = Field(
        default=None,
        description="Path to SQLite database file (default: messages.db in current directory)",
    )
    message_retention_days: int = Field(
        default=30,
        description="Number of days to retain messages in database",
        ge=1,
    )

    # Webhook settings
    webhook_timeout: int = Field(
        default=10,
        description="Timeout in seconds for webhook requests",
        ge=1,
        le=60,
    )
    webhook_max_retries: int = Field(
        default=3,
        description="Maximum number of retries for failed webhook requests",
        ge=0,
        le=10,
    )
    webhook_retry_delay: float = Field(
        default=2.0,
        description="Delay in seconds between webhook retries",
        ge=0.1,
        le=60.0,
    )

    # Message queue settings
    message_queue_max_size: int = Field(
        default=1000,
        description="Maximum number of messages in queue (0 = unlimited)",
        ge=0,
    )
    message_queue_max_retries: int = Field(
        default=3,
        description="Maximum number of retries for failed message sends",
        ge=0,
        le=10,
    )
    message_queue_retry_delay: float = Field(
        default=2.0,
        description="Delay in seconds between message retries",
        ge=0.1,
        le=60.0,
    )
    message_cleanup_interval_hours: int = Field(
        default=24,
        description="Interval in hours between automatic message cleanup runs",
        ge=1,
    )

    @field_validator("connection_type", mode="before")
    @classmethod
    def validate_connection_type(cls, v: str) -> ConnectionType:
        """Validate and normalize connection type."""
        if isinstance(v, str):
            v = v.lower()
            if v in ("usb", "serial"):
                return ConnectionType.USB
            if v == "tcp":
                return ConnectionType.TCP
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()

    @field_validator("api_keys", mode="before")
    @classmethod
    def parse_api_keys(cls, v: str | list[str] | None) -> list[str] | None:
        """Parse API keys from comma-separated string or list."""
        if v is None:
            return None
        if isinstance(v, str):
            # Split by comma and strip whitespace
            keys = [key.strip() for key in v.split(",") if key.strip()]
            return keys if keys else None
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str] | None) -> list[str]:
        """Parse CORS origins from comma-separated string or list."""
        if v is None:
            return []
        if isinstance(v, str):
            # Split by comma and strip whitespace
            origins = [origin.strip() for origin in v.split(",") if origin.strip()]
            return origins
        return v if isinstance(v, list) else []

    @field_validator("blacklisted_channels", mode="before")
    @classmethod
    def parse_blacklisted_channels(cls, v: str | list[str] | None) -> list[str] | None:
        """Parse blacklisted channels from comma-separated string or list."""
        if v is None:
            return None
        if isinstance(v, str):
            if not v.strip():
                return None
            # Split by comma and strip whitespace
            channels = [ch.strip() for ch in v.split(",") if ch.strip()]
            return channels if channels else None
        if isinstance(v, list):
            # Already a list, return as-is (but ensure all items are strings)
            channels = [str(ch).strip() for ch in v if str(ch).strip()]
            return channels if channels else None
        return None

    def validate_connection_settings(self) -> tuple[bool, Optional[str]]:
        """
        Validate that connection settings are properly configured.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if self.connection_type == ConnectionType.USB:
            if not self.usb_device:
                return False, "USB device path is required when connection_type is 'usb'"
        elif self.connection_type == ConnectionType.TCP:
            if not self.tcp_host:
                return False, "TCP host is required when connection_type is 'tcp'"

        return True, None


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    return logger

