from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.sql import func

from database import Base


class ManageBacConnection(Base):
    """One encrypted personal iCal subscription per IBuddy user."""

    __tablename__ = "managebac_connections"
    __table_args__ = (
        Index("ix_managebac_connection_due", "enabled", "next_sync_at"),
        Index("ix_managebac_connection_lease", "lease_expires_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    encrypted_feed_url = Column(Text, nullable=False)
    feed_host = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="pending", server_default=text("'pending'"))
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    sync_interval_minutes = Column(Integer, nullable=False, default=10, server_default=text("10"))
    etag = Column(String(512), nullable=True)
    last_modified = Column(String(255), nullable=True)
    next_sync_at = Column(DateTime, nullable=True)
    last_sync_started_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error_code = Column(String(80), nullable=True)
    last_error_detail = Column(String(500), nullable=True)
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ManageBacTaskLink(Base):
    """Stable mapping from an iCalendar UID to an IBuddy task."""

    __tablename__ = "managebac_task_links"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_uid",
            name="uq_managebac_connection_uid",
        ),
        Index("ix_managebac_link_connection_seen", "connection_id", "last_seen_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(
        Integer,
        ForeignKey("managebac_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_uid = Column(String(512), nullable=False)
    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    remote_hash = Column(String(64), nullable=False)
    remote_sequence = Column(Integer, nullable=True)
    remote_last_modified = Column(DateTime, nullable=True)
    remote_snapshot = Column(JSON, nullable=False, default=dict)
    source_url = Column(Text, nullable=True)
    remote_state = Column(String(20), nullable=False, default="active", server_default=text("'active'"))
    first_seen_at = Column(DateTime, nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime, nullable=False, server_default=func.now())
    missing_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ManageBacSyncRun(Base):
    """Bounded, token-free audit record for one synchronization attempt."""

    __tablename__ = "managebac_sync_runs"
    __table_args__ = (
        Index("ix_managebac_run_connection_started", "connection_id", "started_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(
        Integer,
        ForeignKey("managebac_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="running", server_default=text("'running'"))
    http_status = Column(Integer, nullable=True)
    total_items = Column(Integer, nullable=False, default=0, server_default=text("0"))
    added_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    updated_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    unchanged_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    cancelled_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    skipped_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    error_code = Column(String(80), nullable=True)
    error_detail = Column(String(500), nullable=True)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
