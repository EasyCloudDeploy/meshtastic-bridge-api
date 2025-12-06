"""Webhook handler for incoming messages."""

import hashlib
import hmac
import ipaddress
import json
import logging
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import httpx

from .config import Settings
from .database import Database

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handles webhook delivery for incoming messages."""

    # Private IP ranges and localhost that should be blocked
    _BLOCKED_NETWORKS = [
        ipaddress.IPv4Network("127.0.0.0/8"),  # localhost
        ipaddress.IPv4Network("10.0.0.0/8"),  # private
        ipaddress.IPv4Network("172.16.0.0/12"),  # private
        ipaddress.IPv4Network("192.168.0.0/16"),  # private
        ipaddress.IPv4Network("169.254.0.0/16"),  # link-local
        ipaddress.IPv4Network("0.0.0.0/8"),  # invalid
    ]

    def __init__(self, database: Database, settings: Settings) -> None:
        """
        Initialize webhook handler.

        Args:
            database: Database instance
            settings: Application settings
        """
        self.database = database
        self.settings = settings
        self._client = httpx.Client(timeout=settings.webhook_timeout)

    @classmethod
    def validate_webhook_url(cls, url: str) -> tuple[bool, Optional[str]]:
        """
        Validate webhook URL to prevent SSRF attacks.

        Args:
            url: Webhook URL to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            parsed = urlparse(url)
        except Exception as e:
            return False, f"Invalid URL format: {e}"

        # Only allow http and https schemes
        if parsed.scheme not in ("http", "https"):
            return False, "Only http and https schemes are allowed"

        # Check for localhost or IP addresses
        hostname = parsed.hostname
        if not hostname:
            return False, "URL must have a hostname"

        # Block localhost hostnames
        if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False, "Localhost URLs are not allowed for security reasons"

        # Check if hostname is an IP address
        try:
            ip = ipaddress.ip_address(hostname)
            # Block private/internal IP ranges
            for network in cls._BLOCKED_NETWORKS:
                if ip in network:
                    return False, f"Private/internal IP addresses are not allowed: {hostname}"

            # Block IPv6 localhost and private ranges
            if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved:
                return False, f"Private/reserved IP addresses are not allowed: {hostname}"
        except ValueError:
            # Not an IP address, check if it's a valid hostname
            # Allow valid hostnames (DNS will resolve)
            pass

        return True, None

    def deliver_message(
        self,
        message_text: str,
        channel: str,
        sender_id: Optional[str] = None,
        sender_name: Optional[str] = None,
    ) -> None:
        """
        Deliver message to configured webhooks.

        Args:
            message_text: Message content
            channel: Channel name
            sender_id: Optional sender node ID
            sender_name: Optional sender name
        """
        # Get webhooks for this channel
        webhooks = self.database.get_webhooks(channel=channel, enabled_only=True)

        if not webhooks:
            return

        # Prepare payload
        payload = {
            "message": message_text,
            "channel": channel,
            "timestamp": time.time(),
        }
        if sender_id:
            payload["sender_id"] = sender_id
        if sender_name:
            payload["sender_name"] = sender_name

        # Deliver to each webhook in separate thread
        for webhook in webhooks:
            threading.Thread(
                target=self._deliver_to_webhook,
                args=(webhook, payload),
                daemon=True,
            ).start()

    def _deliver_to_webhook(self, webhook: dict, payload: dict) -> None:
        """
        Deliver payload to a specific webhook with retry logic.

        Args:
            webhook: Webhook configuration dictionary
            payload: Payload to deliver
        """
        url = webhook["url"]
        secret = webhook.get("secret")
        webhook_id = webhook["id"]

        # Validate URL before making request (defense in depth)
        is_valid, error_msg = self.validate_webhook_url(url)
        if not is_valid:
            logger.error(f"Webhook {webhook_id} has invalid URL: {error_msg}")
            return

        # Add signature if secret is provided
        headers = {"Content-Type": "application/json"}
        if secret:
            payload_str = json.dumps(payload, sort_keys=True)
            signature = hmac.new(
                secret.encode(), payload_str.encode(), hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        # Retry logic
        for attempt in range(self.settings.webhook_max_retries + 1):
            try:
                response = self._client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                logger.info(f"Webhook delivered successfully to {url} (attempt {attempt + 1})")
                return
            except Exception as e:
                if attempt < self.settings.webhook_max_retries:
                    logger.warning(
                        f"Webhook delivery failed to {url} (attempt {attempt + 1}): {e}. Retrying..."
                    )
                    time.sleep(self.settings.webhook_retry_delay)
                else:
                    logger.error(
                        f"Webhook delivery failed to {url} after {self.settings.webhook_max_retries + 1} attempts: {e}"
                    )

