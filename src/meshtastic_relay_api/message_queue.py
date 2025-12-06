"""Message queue for handling concurrent message requests."""

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from .config import Settings
from .meshtastic_manager import ChannelNotFoundError, MeshtasticManager

logger = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    """Represents a message in the queue."""

    message_id: str
    message: str
    channel: str
    timestamp: float
    retry_count: int = 0


class MessageQueue:
    """Thread-safe message queue with background processor."""

    def __init__(self, meshtastic_manager: MeshtasticManager, settings: Settings) -> None:
        """
        Initialize the message queue.

        Args:
            meshtastic_manager: Meshtastic connection manager
            settings: Application settings
        """
        self.meshtastic_manager = meshtastic_manager
        self.settings = settings
        self._queue: queue.Queue[QueuedMessage] = queue.Queue()
        self._processing = False
        self._processor_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._max_retries = 3
        self._retry_delay = 2.0  # seconds

    def start(self) -> None:
        """Start the background message processor."""
        with self._lock:
            if self._processing:
                logger.warning("Message queue processor already running")
                return

            self._processing = True
            self._processor_thread = threading.Thread(
                target=self._process_messages, daemon=True, name="MessageQueueProcessor"
            )
            self._processor_thread.start()
            logger.info("Message queue processor started")

    def stop(self) -> None:
        """Stop the background message processor."""
        with self._lock:
            if not self._processing:
                return

            self._processing = False
            if self._processor_thread:
                self._processor_thread.join(timeout=5.0)
            logger.info("Message queue processor stopped")

    def enqueue(
        self, message: str, channel: str
    ) -> tuple[str, int]:
        """
        Add a message to the queue.

        Args:
            message: Message text to send
            channel: Channel name (required)

        Returns:
            Tuple of (message_id, queue_size)
        """
        message_id = str(uuid.uuid4())
        channel_name = channel

        queued_message = QueuedMessage(
            message_id=message_id,
            message=message,
            channel=channel_name,
            timestamp=time.time(),
        )

        self._queue.put(queued_message)
        queue_size = self._queue.qsize()

        logger.info(
            f"Message queued: {message_id[:8]}... (queue size: {queue_size}, "
            f"channel: {channel_name})"
        )

        return message_id, queue_size

    def get_queue_size(self) -> int:
        """
        Get current queue size.

        Returns:
            Number of messages in queue
        """
        return self._queue.qsize()

    def is_processing(self) -> bool:
        """
        Check if processor is running.

        Returns:
            True if processing, False otherwise
        """
        return self._processing

    def _process_messages(self) -> None:
        """Background thread that processes messages from the queue."""
        logger.info("Message queue processor thread started")

        while self._processing:
            try:
                # Get message from queue with timeout to allow checking _processing flag
                try:
                    queued_message = self._queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Ensure we're connected
                if not self.meshtastic_manager.is_connected():
                    logger.warning("Not connected to Meshtastic device, attempting to reconnect...")
                    if not self.meshtastic_manager.connect():
                        logger.error("Failed to connect, requeuing message")
                        queued_message.retry_count += 1
                        if queued_message.retry_count < self._max_retries:
                            self._queue.put(queued_message)
                            time.sleep(self._retry_delay)
                        else:
                            logger.error(
                                f"Message {queued_message.message_id} exceeded max retries, "
                                "dropping message"
                            )
                        continue

                # Send the message
                try:
                    success = self.meshtastic_manager.send_message(
                        message=queued_message.message,
                        channel=queued_message.channel,
                    )

                    if success:
                        logger.info(
                            f"Successfully processed message {queued_message.message_id[:8]}..."
                        )
                    else:
                        # Retry logic for transient failures
                        queued_message.retry_count += 1
                        if queued_message.retry_count < self._max_retries:
                            logger.warning(
                                f"Failed to send message {queued_message.message_id[:8]}..., "
                                f"retrying ({queued_message.retry_count}/{self._max_retries})"
                            )
                            self._queue.put(queued_message)
                            time.sleep(self._retry_delay)
                        else:
                            logger.error(
                                f"Message {queued_message.message_id[:8]}... exceeded max retries, "
                                "dropping message"
                            )
                except ChannelNotFoundError as e:
                    # Channel not found - don't retry, just log and drop
                    logger.error(
                        f"Message {queued_message.message_id[:8]}... dropped: {e}"
                    )

                # Mark task as done
                self._queue.task_done()

            except Exception as e:
                logger.error(f"Error in message queue processor: {e}", exc_info=True)
                time.sleep(1.0)

        logger.info("Message queue processor thread stopped")

