"""SQLite3 database for message persistence."""

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import Settings

logger = logging.getLogger(__name__)


class Database:
    """SQLite3 database manager for message storage."""

    def __init__(self, settings: Settings, db_path: Optional[str] = None) -> None:
        """
        Initialize the database.

        Args:
            settings: Application settings
            db_path: Optional path to database file (default: messages.db in current directory)
        """
        self.settings = settings
        self.db_path = db_path or "messages.db"
        self._lock = threading.Lock()
        self._init_database()

    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Messages table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    message_text TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    sender_id TEXT,
                    sender_name TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    sent_at REAL,
                    received_at REAL
                )
            """
            )
            # Scheduled messages table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id TEXT PRIMARY KEY,
                    message_text TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    scheduled_at REAL NOT NULL,
                    recurrence_pattern TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_run_at REAL
                )
            """
            )
            # Webhooks table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS webhooks (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    channel_filter TEXT,
                    secret TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                )
            """
            )
            # Indexes for performance
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_direction ON messages(direction)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_messages_scheduled_at ON scheduled_messages(scheduled_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_messages_status ON scheduled_messages(status)"
            )
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Get a database connection with proper locking."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def save_message(
        self,
        message_id: str,
        message_text: str,
        channel: str,
        direction: str,
        sender_id: Optional[str] = None,
        sender_name: Optional[str] = None,
        status: str = "sent",
        sent_at: Optional[float] = None,
        received_at: Optional[float] = None,
    ) -> None:
        """
        Save a message to the database.

        Args:
            message_id: Unique message identifier
            message_text: Message content
            channel: Channel name
            direction: 'sent' or 'received'
            sender_id: Optional sender node ID
            sender_name: Optional sender name
            status: Message status (sent, received, failed, etc.)
            sent_at: Timestamp when message was sent
            received_at: Timestamp when message was received
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages 
                (id, message_text, channel, direction, sender_id, sender_name, status, created_at, sent_at, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message_id,
                    message_text,
                    channel,
                    direction,
                    sender_id,
                    sender_name,
                    status,
                    time.time(),
                    sent_at,
                    received_at,
                ),
            )
            conn.commit()

    def count_messages(
        self,
        channel: Optional[str] = None,
        direction: Optional[str] = None,
        start_date: Optional[float] = None,
        end_date: Optional[float] = None,
    ) -> int:
        """
        Count messages matching the given filters.

        Args:
            channel: Filter by channel name
            direction: Filter by direction ('sent' or 'received')
            start_date: Filter messages after this timestamp
            end_date: Filter messages before this timestamp

        Returns:
            Total number of messages matching the filters
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT COUNT(*) FROM messages WHERE 1=1"
            params = []

            if channel:
                query += " AND channel = ?"
                params.append(channel)
            if direction:
                query += " AND direction = ?"
                params.append(direction)
            if start_date:
                query += " AND created_at >= ?"
                params.append(start_date)
            if end_date:
                query += " AND created_at <= ?"
                params.append(end_date)

            cursor.execute(query, params)
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_messages(
        self,
        limit: int = 100,
        offset: int = 0,
        channel: Optional[str] = None,
        direction: Optional[str] = None,
        start_date: Optional[float] = None,
        end_date: Optional[float] = None,
    ) -> list[dict]:
        """
        Retrieve messages from the database.

        Args:
            limit: Maximum number of messages to return
            offset: Offset for pagination
            channel: Filter by channel name
            direction: Filter by direction ('sent' or 'received')
            start_date: Filter messages after this timestamp
            end_date: Filter messages before this timestamp

        Returns:
            List of message dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM messages WHERE 1=1"
            params = []

            if channel:
                query += " AND channel = ?"
                params.append(channel)
            if direction:
                query += " AND direction = ?"
                params.append(direction)
            if start_date:
                query += " AND created_at >= ?"
                params.append(start_date)
            if end_date:
                query += " AND created_at <= ?"
                params.append(end_date)

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_message(self, message_id: str) -> Optional[dict]:
        """
        Get a single message by ID.

        Args:
            message_id: Message identifier

        Returns:
            Message dictionary or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_message_status(
        self, message_id: str, status: str, sent_at: Optional[float] = None
    ) -> None:
        """
        Update message status.

        Args:
            message_id: Message identifier
            status: New status
            sent_at: Optional timestamp when message was sent
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if sent_at:
                cursor.execute(
                    "UPDATE messages SET status = ?, sent_at = ? WHERE id = ?",
                    (status, sent_at, message_id),
                )
            else:
                cursor.execute(
                    "UPDATE messages SET status = ? WHERE id = ?", (status, message_id)
                )
            conn.commit()

    def cleanup_old_messages(self, retention_days: int = 30) -> int:
        """
        Delete messages older than retention period.

        Args:
            retention_days: Number of days to retain messages

        Returns:
            Number of messages deleted
        """
        cutoff_time = time.time() - (retention_days * 24 * 60 * 60)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE created_at < ?", (cutoff_time,))
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old messages (older than {retention_days} days)")
            return deleted

    def save_scheduled_message(
        self,
        message_id: str,
        message_text: str,
        channel: str,
        scheduled_at: float,
        recurrence_pattern: Optional[str] = None,
        status: str = "pending",
    ) -> None:
        """
        Save a scheduled message.

        Args:
            message_id: Unique message identifier
            message_text: Message content
            channel: Channel name
            scheduled_at: Timestamp when message should be sent
            recurrence_pattern: Optional cron-like recurrence pattern
            status: Status (pending, completed, cancelled)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scheduled_messages 
                (id, message_text, channel, scheduled_at, recurrence_pattern, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message_id,
                    message_text,
                    channel,
                    scheduled_at,
                    recurrence_pattern,
                    status,
                    time.time(),
                ),
            )
            conn.commit()

    def get_pending_scheduled_messages(self, current_time: float) -> list[dict]:
        """
        Get scheduled messages that are due to be sent.

        Args:
            current_time: Current timestamp

        Returns:
            List of scheduled message dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scheduled_messages 
                WHERE status = 'pending' AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
            """,
                (current_time,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def update_scheduled_message_status(
        self, message_id: str, status: str, last_run_at: Optional[float] = None
    ) -> None:
        """
        Update scheduled message status.

        Args:
            message_id: Message identifier
            status: New status
            last_run_at: Optional timestamp of last run
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if last_run_at:
                cursor.execute(
                    """
                    UPDATE scheduled_messages 
                    SET status = ?, last_run_at = ?
                    WHERE id = ?
                """,
                    (status, last_run_at, message_id),
                )
            else:
                cursor.execute(
                    "UPDATE scheduled_messages SET status = ? WHERE id = ?",
                    (status, message_id),
                )
            conn.commit()

    def add_webhook(
        self,
        webhook_id: str,
        url: str,
        channel_filter: Optional[str] = None,
        secret: Optional[str] = None,
    ) -> None:
        """
        Add a webhook configuration.

        Args:
            webhook_id: Unique webhook identifier
            url: Webhook URL
            channel_filter: Optional channel name filter
            secret: Optional secret for webhook authentication
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO webhooks (id, url, channel_filter, secret, enabled, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
            """,
                (webhook_id, url, channel_filter, secret, time.time()),
            )
            conn.commit()

    def get_webhooks(
        self, channel: Optional[str] = None, enabled_only: bool = True
    ) -> list[dict]:
        """
        Get webhook configurations.

        Args:
            channel: Optional channel filter
            enabled_only: Only return enabled webhooks

        Returns:
            List of webhook dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM webhooks WHERE 1=1"
            params = []

            if enabled_only:
                query += " AND enabled = 1"
            if channel:
                query += " AND (channel_filter IS NULL OR channel_filter = ?)"
                params.append(channel)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def delete_webhook(self, webhook_id: str) -> None:
        """
        Delete a webhook.

        Args:
            webhook_id: Webhook identifier
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            conn.commit()

