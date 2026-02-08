"""
Tests for sync control plane (sync_controller.py).
"""

import json
import time
from pathlib import Path

import pytest

from sync_controller import (
    ControlStore,
    SyncController,
    SyncPolicy,
    SyncResult,
)


class TestSyncPolicy:
    """Test suite for SyncPolicy."""

    def test_default_policy(self):
        policy = SyncPolicy()
        assert policy.max_retries == 3
        assert policy.retry_backoff == "exponential"
        assert policy.retry_delay_seconds == 2.0
        assert policy.timeout_seconds == 300.0
        assert policy.on_failure == "log"
        assert policy.webhook_url is None

    def test_exponential_backoff(self):
        policy = SyncPolicy(retry_delay_seconds=1.0, retry_backoff="exponential")
        assert policy.compute_delay(0) == 1.0
        assert policy.compute_delay(1) == 2.0
        assert policy.compute_delay(2) == 4.0
        assert policy.compute_delay(3) == 8.0

    def test_linear_backoff(self):
        policy = SyncPolicy(retry_delay_seconds=2.0, retry_backoff="linear")
        assert policy.compute_delay(0) == 2.0
        assert policy.compute_delay(1) == 4.0
        assert policy.compute_delay(2) == 6.0

    def test_fixed_backoff(self):
        policy = SyncPolicy(retry_delay_seconds=5.0, retry_backoff="fixed")
        assert policy.compute_delay(0) == 5.0
        assert policy.compute_delay(1) == 5.0
        assert policy.compute_delay(2) == 5.0

    def test_round_trip_dict(self):
        policy = SyncPolicy(max_retries=5, webhook_url="https://example.com/hook")
        d = policy.to_dict()
        restored = SyncPolicy.from_dict(d)
        assert restored.max_retries == 5
        assert restored.webhook_url == "https://example.com/hook"

    def test_from_dict_defaults(self):
        policy = SyncPolicy.from_dict({})
        assert policy.max_retries == 3
        assert policy.retry_backoff == "exponential"


class TestControlStore:
    """Test suite for DuckDB-backed ControlStore."""

    @pytest.fixture
    def store(self, tmp_path):
        s = ControlStore(tmp_path / "control.duckdb")
        yield s
        s.close()

    def test_schema_creation(self, store):
        """Tables are created on first access."""
        conn = store._get_conn()
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "sync_events" in table_names
        assert "sync_schedules" in table_names
        assert "control_meta" in table_names

    def test_record_start_and_complete_success(self, store):
        store.record_start("evt-1", "remote_push", "gs://bucket/path")
        result = SyncResult(success=True, changes_added=3, changes_modified=1)
        store.record_complete("evt-1", result)

        events = store.get_history()
        assert len(events) == 1
        assert events[0]["id"] == "evt-1"
        assert events[0]["status"] == "completed"
        assert events[0]["changes_added"] == 3
        assert events[0]["changes_modified"] == 1

    def test_record_failure(self, store):
        store.record_start("evt-2", "snapshot", "default/cities")
        result = SyncResult(success=False, error_message="Connection refused")
        store.record_complete("evt-2", result)

        events = store.get_history()
        assert events[0]["status"] == "failed"
        assert "Connection refused" in events[0]["error_message"]

    def test_history_filter_by_type(self, store):
        store.record_start("a", "remote_push", "gs://bucket")
        store.record_complete("a", SyncResult(success=True))
        store.record_start("b", "snapshot", "default/cities")
        store.record_complete("b", SyncResult(success=True))

        push_events = store.get_history(sync_type="remote_push")
        assert len(push_events) == 1
        assert push_events[0]["type"] == "remote_push"

    def test_history_filter_by_target(self, store):
        store.record_start("a", "snapshot", "default/cities")
        store.record_complete("a", SyncResult(success=True))
        store.record_start("b", "snapshot", "default/boundaries")
        store.record_complete("b", SyncResult(success=True))

        events = store.get_history(target="default/cities")
        assert len(events) == 1

    def test_history_limit(self, store):
        for i in range(10):
            store.record_start(f"evt-{i}", "snapshot", "default/res")
            store.record_complete(f"evt-{i}", SyncResult(success=True))

        events = store.get_history(limit=3)
        assert len(events) == 3

    def test_history_ordering(self, store):
        """Most recent events first."""
        store.record_start("old", "snapshot", "default/res")
        store.record_complete("old", SyncResult(success=True))
        store.record_start("new", "snapshot", "default/res")
        store.record_complete("new", SyncResult(success=True))

        events = store.get_history()
        assert events[0]["id"] == "new"
        assert events[1]["id"] == "old"

    def test_health_summary(self, store):
        store.record_start("a", "remote_push", "gs://bucket")
        store.record_complete("a", SyncResult(success=True))
        store.record_start("b", "remote_push", "gs://bucket")
        store.record_complete("b", SyncResult(success=False, error_message="err"))

        summary = store.get_health_summary(hours=24)
        assert summary["period_hours"] == 24
        assert len(summary["by_type"]) == 1
        row = summary["by_type"][0]
        assert row["type"] == "remote_push"
        assert row["total_runs"] == 2
        assert row["succeeded"] == 1
        assert row["failed"] == 1

    def test_get_last_event(self, store):
        store.record_start("a", "snapshot", "default/cities")
        store.record_complete("a", SyncResult(success=True))
        store.record_start("b", "snapshot", "default/cities")
        store.record_complete("b", SyncResult(success=False, error_message="err"))

        last = store.get_last_event("snapshot", "default/cities")
        assert last["id"] == "b"
        assert last["status"] == "failed"

    def test_get_last_event_not_found(self, store):
        assert store.get_last_event("snapshot", "nonexistent") is None

    def test_metadata_stored_as_json(self, store):
        store.record_start("m", "snapshot", "default/cities")
        result = SyncResult(success=True, metadata={"origin_type": "arcgis"})
        store.record_complete("m", result)

        events = store.get_history()
        meta = json.loads(events[0]["metadata"])
        assert meta["origin_type"] == "arcgis"

    def test_upsert_schedule(self, store):
        policy = SyncPolicy(max_retries=5)
        store.upsert_schedule("nightly-sync", "catalog_sync", "earth-search",
                              cron_expr="0 0 * * *", policy=policy)

        schedules = store.list_schedules()
        assert len(schedules) == 1
        assert schedules[0]["name"] == "nightly-sync"
        assert schedules[0]["cron_expr"] == "0 0 * * *"

        parsed_policy = json.loads(schedules[0]["policy_json"])
        assert parsed_policy["max_retries"] == 5

    def test_prune_events(self, store):
        for i in range(20):
            store.record_start(f"evt-{i}", "snapshot", "default/res")
            store.record_complete(f"evt-{i}", SyncResult(success=True))

        store.prune_events(keep_last=5)
        events = store.get_history(limit=100)
        assert len(events) == 5

    def test_idempotent_schema(self, tmp_path):
        """Opening the same DB twice doesn't fail."""
        db_path = tmp_path / "control.duckdb"
        s1 = ControlStore(db_path)
        s1.record_start("a", "snapshot", "x")
        s1.close()

        s2 = ControlStore(db_path)
        events = s2.get_history()
        assert len(events) == 1
        s2.close()


class TestSyncController:
    """Test suite for SyncController orchestration."""

    @pytest.fixture
    def portolan_dir(self, tmp_path):
        d = tmp_path / ".portolan"
        d.mkdir()
        return d

    @pytest.fixture
    def controller(self, portolan_dir):
        policy = SyncPolicy(max_retries=2, retry_delay_seconds=0.01)
        c = SyncController(portolan_dir, policy=policy)
        yield c
        c.close()

    def test_successful_execution(self, controller):
        call_count = 0

        def success_fn():
            nonlocal call_count
            call_count += 1
            return SyncResult(success=True, changes_added=5)

        result = controller.execute("snapshot", "default/cities", success_fn)
        assert result.success
        assert result.changes_added == 5
        assert call_count == 1

        # Event recorded
        events = controller.history()
        assert len(events) == 1
        assert events[0]["status"] == "completed"

    def test_retry_on_exception(self, controller):
        call_count = 0

        def failing_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return SyncResult(success=True)

        result = controller.execute("remote_push", "gs://bucket", failing_fn)
        assert result.success
        assert call_count == 3  # 1 initial + 2 retries

        # All attempts recorded
        events = controller.history(limit=10)
        assert len(events) == 3
        statuses = [e["status"] for e in events]
        assert statuses.count("failed") == 2
        assert statuses.count("completed") == 1

    def test_retry_on_result_failure(self, controller):
        call_count = 0

        def soft_fail_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return SyncResult(success=False, error_message="Temporary issue")
            return SyncResult(success=True)

        result = controller.execute("catalog_sync", "earth-search", soft_fail_fn)
        assert result.success
        assert call_count == 2

    def test_all_retries_exhausted(self, controller):
        def always_fail():
            raise RuntimeError("Permanent failure")

        result = controller.execute("snapshot", "default/broken", always_fail)
        assert not result.success
        assert "Permanent failure" in result.error_message

        events = controller.history(limit=10)
        assert len(events) == 3  # 1 initial + 2 retries
        assert all(e["status"] == "failed" for e in events)

    def test_no_retry_policy(self, portolan_dir):
        policy = SyncPolicy(max_retries=0)
        ctrl = SyncController(portolan_dir, policy=policy)

        call_count = 0

        def fail_once():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        result = ctrl.execute("snapshot", "x", fail_once)
        assert not result.success
        assert call_count == 1
        ctrl.close()

    def test_policy_from_config(self, portolan_dir):
        config = {
            "outputs": {"iceberg": True},
            "sync_policy": {
                "max_retries": 7,
                "retry_backoff": "linear",
                "on_failure": "webhook",
                "webhook_url": "https://example.com/hook",
            },
        }
        (portolan_dir / "config.json").write_text(json.dumps(config))

        ctrl = SyncController(portolan_dir)
        assert ctrl.policy.max_retries == 7
        assert ctrl.policy.retry_backoff == "linear"
        assert ctrl.policy.on_failure == "webhook"
        ctrl.close()

    def test_policy_default_when_no_config(self, portolan_dir):
        ctrl = SyncController(portolan_dir)
        assert ctrl.policy.max_retries == 3
        assert ctrl.policy.retry_backoff == "exponential"
        ctrl.close()

    def test_health_query(self, controller):
        controller.execute("snapshot", "a", lambda: SyncResult(success=True))
        controller.execute("snapshot", "b", lambda: SyncResult(success=True))

        health = controller.health()
        assert health["period_hours"] == 24
        assert len(health["by_type"]) == 1
        assert health["by_type"][0]["succeeded"] == 2

    def test_last_event_query(self, controller):
        controller.execute("snapshot", "default/cities", lambda: SyncResult(success=True, changes_added=10))

        last = controller.last_event("snapshot", "default/cities")
        assert last is not None
        assert last["status"] == "completed"
        assert last["changes_added"] == 10
