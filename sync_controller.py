"""
Sync Control Plane for Portolan.

Provides instrumentation, retry logic, and history tracking for all sync operations.
Uses DuckDB as the backing store for sync events, keeping the project serverless
(every CLI invocation reads/writes to the same .portolan/control.duckdb file).

Sync operation types:
- remote_push:   portolan sync       (push local changes to remote)
- remote_pull:   portolan pull       (pull remote changes to local)
- snapshot:      portolan refresh    (re-fetch data from origin)

Usage:
    controller = SyncController(portolan_dir)
    task = controller.create_task("catalog_sync", target="earth-search")
    result = controller.execute(task, fn=lambda: sync_stac_catalog(...))
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb


# =============================================================================
# Sync Policy
# =============================================================================


@dataclass
class SyncPolicy:
    """Configurable policy for sync operations."""

    max_retries: int = 3
    retry_backoff: str = "exponential"  # exponential, linear, fixed
    retry_delay_seconds: float = 2.0
    timeout_seconds: float = 300.0
    on_failure: str = "log"  # log, webhook
    webhook_url: str | None = None

    def compute_delay(self, attempt: int) -> float:
        """Compute delay before next retry attempt."""
        if self.retry_backoff == "exponential":
            return self.retry_delay_seconds * (2 ** attempt)
        elif self.retry_backoff == "linear":
            return self.retry_delay_seconds * (attempt + 1)
        else:  # fixed
            return self.retry_delay_seconds

    def to_dict(self) -> dict:
        result = {
            "max_retries": self.max_retries,
            "retry_backoff": self.retry_backoff,
            "retry_delay_seconds": self.retry_delay_seconds,
            "timeout_seconds": self.timeout_seconds,
            "on_failure": self.on_failure,
        }
        if self.webhook_url:
            result["webhook_url"] = self.webhook_url
        return result

    @classmethod
    def from_dict(cls, data: dict) -> SyncPolicy:
        return cls(
            max_retries=data.get("max_retries", 3),
            retry_backoff=data.get("retry_backoff", "exponential"),
            retry_delay_seconds=data.get("retry_delay_seconds", 2.0),
            timeout_seconds=data.get("timeout_seconds", 300.0),
            on_failure=data.get("on_failure", "log"),
            webhook_url=data.get("webhook_url"),
        )


DEFAULT_POLICY = SyncPolicy()


# =============================================================================
# Sync Result
# =============================================================================


@dataclass
class SyncResult:
    """Result of a sync operation, returned by the wrapped function."""

    success: bool
    changes_added: int = 0
    changes_modified: int = 0
    changes_deleted: int = 0
    error_message: str | None = None
    metadata: dict = field(default_factory=dict)


# =============================================================================
# DuckDB Control Store
# =============================================================================


class ControlStore:
    """DuckDB-backed storage for sync events and schedules."""

    SCHEMA_VERSION = 1

    DDL = """
    CREATE TABLE IF NOT EXISTS sync_events (
        id              VARCHAR PRIMARY KEY,
        type            VARCHAR NOT NULL,
        target          VARCHAR NOT NULL,
        status          VARCHAR NOT NULL,
        attempt         INTEGER DEFAULT 1,
        started_at      TIMESTAMP NOT NULL,
        completed_at    TIMESTAMP,
        duration_ms     INTEGER,
        changes_added   INTEGER DEFAULT 0,
        changes_modified INTEGER DEFAULT 0,
        changes_deleted INTEGER DEFAULT 0,
        error_message   VARCHAR,
        metadata        VARCHAR
    );

    CREATE TABLE IF NOT EXISTS sync_schedules (
        name            VARCHAR PRIMARY KEY,
        type            VARCHAR NOT NULL,
        target          VARCHAR NOT NULL,
        cron_expr       VARCHAR,
        policy_json     VARCHAR,
        enabled         BOOLEAN DEFAULT TRUE,
        last_run_id     VARCHAR
    );

    CREATE TABLE IF NOT EXISTS control_meta (
        key             VARCHAR PRIMARY KEY,
        value           VARCHAR NOT NULL
    );
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(self.db_path))
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self):
        conn = self._conn
        # Check if tables exist already
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        if "sync_events" not in table_names:
            conn.execute(self.DDL)
            conn.execute(
                "INSERT OR REPLACE INTO control_meta VALUES ('schema_version', ?)",
                [str(self.SCHEMA_VERSION)],
            )

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- Event logging --

    @staticmethod
    def _utcnow() -> str:
        """UTC timestamp as ISO string (portable, DuckDB-WASM compatible)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    def record_start(
        self,
        event_id: str,
        sync_type: str,
        target: str,
        attempt: int = 1,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO sync_events (id, type, target, status, attempt, started_at)
            VALUES (?, ?, ?, 'started', ?, CAST(? AS TIMESTAMP))
            """,
            [event_id, sync_type, target, attempt, self._utcnow()],
        )

    def record_complete(
        self,
        event_id: str,
        result: SyncResult,
    ) -> None:
        conn = self._get_conn()
        now = self._utcnow()
        conn.execute(
            """
            UPDATE sync_events
            SET status = ?,
                completed_at = CAST(? AS TIMESTAMP),
                duration_ms = EXTRACT(EPOCH FROM (CAST(? AS TIMESTAMP) - started_at)) * 1000,
                changes_added = ?,
                changes_modified = ?,
                changes_deleted = ?,
                error_message = ?,
                metadata = ?
            WHERE id = ?
            """,
            [
                "completed" if result.success else "failed",
                now,
                now,
                result.changes_added,
                result.changes_modified,
                result.changes_deleted,
                result.error_message,
                json.dumps(result.metadata) if result.metadata else None,
                event_id,
            ],
        )

    # -- Query helpers --

    def get_history(
        self,
        sync_type: str | None = None,
        target: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        conn = self._get_conn()
        query = "SELECT * FROM sync_events WHERE 1=1"
        params: list = []

        if sync_type:
            query += " AND type = ?"
            params.append(sync_type)
        if target:
            query += " AND target = ?"
            params.append(target)

        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in rows]

    def get_health_summary(self, hours: int = 24) -> dict:
        """Get health summary for the last N hours."""
        conn = self._get_conn()

        # DuckDB doesn't support parameterized INTERVAL, so we validate and interpolate
        hours = int(hours)
        if hours < 0:
            hours = 24

        summary = conn.execute(
            f"""
            SELECT
                type,
                COUNT(*) as total_runs,
                COUNT(*) FILTER (WHERE status = 'completed') as succeeded,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                AVG(duration_ms) FILTER (WHERE status = 'completed') as avg_duration_ms,
                MAX(completed_at) FILTER (WHERE status = 'completed') as last_success,
                MAX(completed_at) FILTER (WHERE status = 'failed') as last_failure
            FROM sync_events
            WHERE started_at > NOW() - INTERVAL '{hours} hours'
            GROUP BY type
            ORDER BY type
            """,
        ).fetchall()

        columns = [desc[0] for desc in conn.description]
        return {
            "period_hours": hours,
            "by_type": [dict(zip(columns, row)) for row in summary],
        }

    def get_last_event(
        self, sync_type: str, target: str
    ) -> dict | None:
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM sync_events
            WHERE type = ? AND target = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            [sync_type, target],
        ).fetchall()

        if not rows:
            return None

        columns = [desc[0] for desc in conn.description]
        return dict(zip(columns, rows[0]))

    # -- Schedule management --

    def upsert_schedule(
        self,
        name: str,
        sync_type: str,
        target: str,
        cron_expr: str | None = None,
        policy: SyncPolicy | None = None,
    ) -> None:
        conn = self._get_conn()
        policy_json = json.dumps(policy.to_dict()) if policy else None
        conn.execute(
            """
            INSERT OR REPLACE INTO sync_schedules (name, type, target, cron_expr, policy_json, enabled)
            VALUES (?, ?, ?, ?, ?, TRUE)
            """,
            [name, sync_type, target, cron_expr, policy_json],
        )

    def list_schedules(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sync_schedules ORDER BY name"
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in rows]

    def prune_events(self, keep_last: int = 1000) -> int:
        """Delete old events beyond the retention window. Returns count deleted."""
        conn = self._get_conn()
        result = conn.execute(
            """
            DELETE FROM sync_events
            WHERE id NOT IN (
                SELECT id FROM sync_events ORDER BY started_at DESC LIMIT ?
            )
            """,
            [keep_last],
        )
        return result.fetchone()[0] if result.description else 0


# =============================================================================
# Sync Controller
# =============================================================================


class SyncController:
    """
    Orchestrates sync operations with retry, status tracking, and alerting.

    This is the Layer 1 (passive) control plane. It wraps existing sync functions,
    adding instrumentation without changing their behavior. Every CLI invocation
    that performs a sync operation goes through this controller.
    """

    def __init__(self, portolan_dir: Path, policy: SyncPolicy | None = None):
        self.portolan_dir = portolan_dir
        self.policy = policy or self._load_policy()
        self.store = ControlStore(portolan_dir / "control.duckdb")

    def _load_policy(self) -> SyncPolicy:
        """Load sync policy from config.json, falling back to defaults."""
        config_path = self.portolan_dir / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            policy_data = config.get("sync_policy", {})
            if policy_data:
                return SyncPolicy.from_dict(policy_data)
        return DEFAULT_POLICY

    def create_task_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def execute(
        self,
        sync_type: str,
        target: str,
        fn: Callable[[], SyncResult],
        policy: SyncPolicy | None = None,
    ) -> SyncResult:
        """
        Execute a sync operation with retry and event logging.

        Args:
            sync_type: One of remote_push, remote_pull, catalog_sync, snapshot
            target: Identifier for the sync target (URL, catalog name, resource name)
            fn: The actual sync function, wrapped to return SyncResult
            policy: Override policy for this execution (uses controller default otherwise)

        Returns:
            SyncResult from the last attempt
        """
        policy = policy or self.policy
        task_id = self.create_task_id()
        last_result = SyncResult(success=False, error_message="No attempts made")

        for attempt in range(policy.max_retries + 1):
            event_id = f"{task_id}-{attempt}"

            self.store.record_start(event_id, sync_type, target, attempt + 1)

            try:
                last_result = fn()
                self.store.record_complete(event_id, last_result)

                if last_result.success:
                    return last_result

                # Function returned failure but didn't raise — still retry
                if attempt < policy.max_retries:
                    delay = policy.compute_delay(attempt)
                    time.sleep(delay)

            except Exception as e:
                last_result = SyncResult(
                    success=False,
                    error_message=f"{type(e).__name__}: {e}",
                    metadata={"traceback": traceback.format_exc()},
                )
                self.store.record_complete(event_id, last_result)

                if attempt < policy.max_retries:
                    delay = policy.compute_delay(attempt)
                    time.sleep(delay)

        # All attempts exhausted — alert
        self._on_failure(sync_type, target, last_result, policy)
        return last_result

    def _on_failure(
        self,
        sync_type: str,
        target: str,
        result: SyncResult,
        policy: SyncPolicy,
    ) -> None:
        """Handle final failure after all retries exhausted."""
        if policy.on_failure == "webhook" and policy.webhook_url:
            self._fire_webhook(sync_type, target, result, policy.webhook_url)

    def _fire_webhook(
        self,
        sync_type: str,
        target: str,
        result: SyncResult,
        webhook_url: str,
    ) -> None:
        """Send failure notification to a webhook."""
        try:
            import httpx

            payload = {
                "event": "sync_failed",
                "type": sync_type,
                "target": target,
                "error": result.error_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            httpx.post(webhook_url, json=payload, timeout=10)
        except Exception:
            pass  # Webhook is best-effort

    # -- Convenience query methods --

    def history(
        self,
        sync_type: str | None = None,
        target: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        return self.store.get_history(sync_type, target, limit)

    def health(self, hours: int = 24) -> dict:
        return self.store.get_health_summary(hours)

    def last_event(self, sync_type: str, target: str) -> dict | None:
        return self.store.get_last_event(sync_type, target)

    def close(self):
        self.store.close()
