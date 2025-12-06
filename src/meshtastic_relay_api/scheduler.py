"""Scheduler for processing scheduled messages."""

import logging
import threading
import time
import uuid
from typing import Optional

from .config import Settings
from .database import Database
from .message_queue import MessageQueue
from .meshtastic_manager import MeshtasticManager

logger = logging.getLogger(__name__)


class MessageScheduler:
    """Background scheduler for processing scheduled messages."""

    def __init__(
        self,
        database: Database,
        message_queue: MessageQueue,
        meshtastic_manager: MeshtasticManager,
        settings: Settings,
    ) -> None:
        """
        Initialize the scheduler.

        Args:
            database: Database instance
            message_queue: Message queue instance
            meshtastic_manager: Meshtastic manager instance
            settings: Application settings
        """
        self.database = database
        self.message_queue = message_queue
        self.meshtastic_manager = meshtastic_manager
        self.settings = settings
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._check_interval = 10.0  # Check every 10 seconds
        self._last_cleanup_time = 0.0
        self._cleanup_interval = settings.message_cleanup_interval_hours * 3600.0  # Convert hours to seconds

    def start(self) -> None:
        """Start the scheduler."""
        with self._lock:
            if self._running:
                logger.warning("Scheduler already running")
                return

            self._running = True
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="MessageScheduler"
            )
            self._thread.start()
            logger.info("Message scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        with self._lock:
            if not self._running:
                return

            self._running = False
            if self._thread:
                self._thread.join(timeout=5.0)
            logger.info("Message scheduler stopped")

    def _run(self) -> None:
        """Main scheduler loop."""
        logger.info("Message scheduler thread started")

        while self._running:
            try:
                current_time = time.time()
                pending_messages = self.database.get_pending_scheduled_messages(current_time)

                for scheduled_msg in pending_messages:
                    try:
                        # Enqueue the message
                        message_id, queue_position = self.message_queue.enqueue(
                            message=scheduled_msg["message_text"],
                            channel=scheduled_msg["channel"],
                        )

                        logger.info(
                            f"Scheduled message {scheduled_msg['id']} enqueued as {message_id}"
                        )

                        # Update scheduled message status
                        if scheduled_msg.get("recurrence_pattern"):
                            # For recurring messages, update last_run_at but keep status as pending
                            # (recurrence logic would need to update scheduled_at here)
                            self.database.update_scheduled_message_status(
                                scheduled_msg["id"], "pending", current_time
                            )
                        else:
                            # One-time message, mark as completed
                            self.database.update_scheduled_message_status(
                                scheduled_msg["id"], "completed", current_time
                            )

                    except Exception as e:
                        logger.error(
                            f"Error processing scheduled message {scheduled_msg['id']}: {e}",
                            exc_info=True,
                        )
                        # Mark as failed
                        self.database.update_scheduled_message_status(
                            scheduled_msg["id"], "failed"
                        )

                # Run cleanup if interval has passed
                current_time = time.time()
                if current_time - self._last_cleanup_time >= self._cleanup_interval:
                    try:
                        deleted = self.database.cleanup_old_messages(
                            retention_days=self.settings.message_retention_days
                        )
                        if deleted > 0:
                            logger.info(f"Automatic cleanup: deleted {deleted} old messages")
                        self._last_cleanup_time = current_time
                    except Exception as e:
                        logger.error(f"Error during automatic cleanup: {e}", exc_info=True)

                # Sleep until next check
                time.sleep(self._check_interval)

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                time.sleep(self._check_interval)

        logger.info("Message scheduler thread stopped")

