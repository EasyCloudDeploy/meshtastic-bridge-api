"""Meshtastic device connection manager."""

import logging
import threading
import time
from typing import Optional

import meshtastic.serial_interface
import meshtastic.tcp_interface

from .config import ConnectionType, Settings

logger = logging.getLogger(__name__)


class ChannelNotFoundError(Exception):
    """Exception raised when a channel is not found on the device."""

    pass


class MeshtasticManager:
    """Manages connection to Meshtastic device via USB or TCP."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialize the Meshtastic manager.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.interface: Optional[
            meshtastic.serial_interface.SerialInterface | meshtastic.tcp_interface.TCPInterface
        ] = None
        self._lock = threading.Lock()
        self._connected = False
        self._connection_attempts = 0
        self._max_connection_attempts = 3

    def connect(self) -> bool:
        """
        Establish connection to the Meshtastic device.

        Returns:
            True if connection successful, False otherwise
        """
        with self._lock:
            if self._connected and self.interface is not None:
                logger.info("Already connected to Meshtastic device")
                return True

            try:
                if self.settings.connection_type == ConnectionType.USB:
                    if not self.settings.usb_device:
                        logger.error("USB device path not configured")
                        return False

                    logger.info(f"Connecting to USB device: {self.settings.usb_device}")
                    self.interface = meshtastic.serial_interface.SerialInterface(
                        devPath=self.settings.usb_device
                    )


                elif self.settings.connection_type == ConnectionType.TCP:
                    if not self.settings.tcp_host:
                        logger.error("TCP host not configured")
                        return False

                    logger.info(f"Connecting to TCP device: {self.settings.tcp_host}")
                    self.interface = meshtastic.tcp_interface.TCPInterface(hostname=self.settings.tcp_host)

                else:
                    logger.error(f"Unsupported connection type: {self.settings.connection_type}")
                    return False

                # Wait a moment for connection to stabilize
                time.sleep(1)

                # Verify connection by checking if interface has node info
                if self.interface and hasattr(self.interface, "myInfo"):
                    node_info = self.interface.myInfo
                    if node_info and hasattr(node_info, "user"):
                        logger.info(
                            f"Connected to Meshtastic device: "
                            f"{node_info.user.longName if hasattr(node_info.user, 'longName') else 'Unknown'}"
                        )
                        self._connected = True
                        self._connection_attempts = 0
                        return True

                logger.warning("Connected but could not verify device info")
                self._connected = True
                return True

            except Exception as e:
                logger.error(f"Failed to connect to Meshtastic device: {e}", exc_info=True)
                self._connected = False
                self.interface = None
                self._connection_attempts += 1
                return False

    def disconnect(self) -> None:
        """Close connection to Meshtastic device."""
        with self._lock:
            if self.interface is not None:
                try:
                    logger.info("Disconnecting from Meshtastic device")
                    self.interface.close()
                except Exception as e:
                    logger.error(f"Error disconnecting: {e}", exc_info=True)
                finally:
                    self.interface = None
                    self._connected = False

    def is_connected(self) -> bool:
        """
        Check if currently connected to device.

        Returns:
            True if connected, False otherwise
        """
        with self._lock:
            return self._connected and self.interface is not None

    def send_message(
        self, message: str, channel: str, channel_index: Optional[int] = None
    ) -> bool:
        """
        Send a message to the Meshtastic device.

        Args:
            message: Message text to send (max 200 characters)
            channel: Channel name (required)
            channel_index: Channel index (optional, will be looked up if not provided)

        Returns:
            True if message sent successfully, False otherwise
        """
        with self._lock:
            if not self._connected or self.interface is None:
                logger.error("Not connected to Meshtastic device")
                # Try to reconnect
                if not self.connect():
                    return False

            try:
                # Determine channel index
                target_channel_index = channel_index
                if target_channel_index is None:
                    target_channel_index = self._get_channel_index(channel)

                if target_channel_index is None:
                    error_msg = (
                        f"Channel '{channel}' not found on device. "
                        "Channel name must match exactly (case-sensitive)."
                    )
                    logger.error(error_msg)
                    raise ChannelNotFoundError(error_msg)

                # Validate message length
                if len(message) > self.settings.max_message_length:
                    logger.error(
                        f"Message exceeds maximum length of {self.settings.max_message_length} characters"
                    )
                    return False

                # Debug/dry-run mode - log details without sending
                if self.settings.debug_mode:
                    from .log_utils import sanitize_message
                    sanitized_msg = sanitize_message(message, self.settings)
                    
                    logger.warning("=" * 60)
                    logger.warning("🔍 DEBUG MODE - Message NOT sent (dry-run)")
                    logger.warning("=" * 60)
                    logger.warning(f"Channel Name:     {channel}")
                    logger.warning(f"Channel Index:    {target_channel_index}")
                    logger.warning(f"Message Length:   {len(message)} characters")
                    logger.warning(f"Message Preview:  {sanitized_msg[:100]}{'...' if len(message) > 100 else ''}")
                    logger.warning("=" * 60)
                    return True  # Return success in debug mode

                # Send the message (sanitized log)
                from .log_utils import sanitize_message

                sanitized_msg = sanitize_message(message, self.settings)
                logger.info(
                    f"Sending message to channel '{channel}' (index {target_channel_index}): {sanitized_msg}"
                )
                self.interface.sendText(
                    text=message,
                    channelIndex=target_channel_index,
                    wantAck=True,
                )

                logger.info("Message sent successfully")
                return True

            except Exception as e:
                logger.error(f"Failed to send message: {e}", exc_info=True)
                # Mark as disconnected on error
                self._connected = False
                return False

    def _get_channel_index(self, channel_name: str) -> Optional[int]:
        """
        Get channel index by channel name.

        Args:
            channel_name: Name of the channel

        Returns:
            Channel index if found, None otherwise
        """
        if self.interface is None:
            return None

        try:
            if hasattr(self.interface, "localNode") and self.interface.localNode:
                channels = getattr(self.interface.localNode, "channels", None)
                if channels:
                    # Log all available channels in debug mode
                    if self.settings.debug_mode:
                        logger.info("=== Available Channels on Device ===")
                        for channel_setting in channels:
                            ch_name = "N/A"
                            ch_index = "N/A"
                            ch_role = "N/A"
                            
                            if hasattr(channel_setting, "index"):
                                ch_index = channel_setting.index
                            if hasattr(channel_setting, "role"):
                                ch_role = channel_setting.role
                            if (
                                hasattr(channel_setting, "settings")
                                and channel_setting.settings
                                and hasattr(channel_setting.settings, "name")
                            ):
                                ch_name = channel_setting.settings.name
                            
                            logger.info(
                                f"  Channel Index {ch_index}: Name='{ch_name}', Role={ch_role}"
                            )
                        logger.info("=====================================")
                    
                    # Find the matching channel
                    for channel_setting in channels:
                        if (
                            hasattr(channel_setting, "settings")
                            and channel_setting.settings
                            and hasattr(channel_setting.settings, "name")
                            and channel_setting.settings.name == channel_name
                        ):
                            found_index = channel_setting.index
                            if self.settings.debug_mode:
                                logger.info(
                                    f"✓ Found channel '{channel_name}' at index {found_index}"
                                )
                            return found_index

            logger.error(
                f"Channel '{channel_name}' not found on device. "
                "Channel name must match exactly (case-sensitive)."
            )
            return None  # Channel not found - do not default to index 0

        except Exception as e:
            logger.error(f"Error looking up channel index: {e}", exc_info=True)
            return None  # Error occurred - do not default to index 0

    def get_connection_info(self) -> dict[str, str | bool]:
        """
        Get current connection information.

        Returns:
            Dictionary with connection information
        """
        with self._lock:
            info: dict[str, str | bool] = {
                "connected": self._connected,
                "connection_type": self.settings.connection_type.value if self._connected else None,
            }

            if self._connected and self.interface and hasattr(self.interface, "myInfo"):
                try:
                    node_info = self.interface.myInfo
                    if node_info and hasattr(node_info, "user"):
                        if hasattr(node_info.user, "longName"):
                            info["device_name"] = node_info.user.longName
                        if hasattr(node_info, "hwModel"):
                            info["hardware_model"] = str(node_info.hwModel)
                except Exception:
                    pass

            return info

