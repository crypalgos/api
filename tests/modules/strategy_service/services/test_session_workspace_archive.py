"""SessionWorkspaceArchive.close() is the only thing standing between a live
session's execution record and permanent data loss on delete -- these tests
exist to pin down the upload -> verify -> delete contract: never delete
local data before an upload is confirmed, and always leave a retryable
local copy on any failure."""

import pytest

from app.config import settings as settings_module
from app.modules.strategy_service.services.session_workspace_archive import (
    SessionWorkspaceArchive,
)


@pytest.fixture(autouse=True)
def _workspace_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings_module.settings, "live_session_workspace_dir", str(tmp_path)
    )
    return tmp_path


class _FakeStorageService:
    """In-memory stand-in for storage_service -- captures every upload so
    tests can assert on exact bytes/keys without a real S3 call."""

    def __init__(self, fail_keys: set[str] | None = None, verify_fail_keys: set[str] | None = None):
        self.uploaded: dict[str, bytes] = {}
        self.fail_keys = fail_keys or set()
        self.verify_fail_keys = verify_fail_keys or set()

    async def upload_raw_payload(self, key: str, data: bytes) -> str:
        if key in self.fail_keys:
            raise RuntimeError(f"simulated upload failure for {key}")
        self.uploaded[key] = data
        return key

    async def object_exists(self, key: str) -> bool:
        if key in self.verify_fail_keys:
            return False
        return key in self.uploaded

    async def download_raw_payload(self, key: str) -> bytes:
        return self.uploaded[key]


def _patch_storage_service(monkeypatch, fake) -> None:
    monkeypatch.setattr(
        "app.modules.strategy_service.services.storage_service.storage_service",
        fake,
    )


async def _make_archive_with_data(strategy_id="strat-1", session_id="sess-1"):
    archive = SessionWorkspaceArchive(strategy_id, session_id)
    archive.append_candle([1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 100.0])
    archive.append_events([{"type": "BAR_CLOSED", "sequence_number": 1}])
    return archive


@pytest.mark.asyncio
async def test_close_uploads_verifies_and_deletes_local_workspace(monkeypatch):
    fake = _FakeStorageService()
    _patch_storage_service(monkeypatch, fake)

    archive = await _make_archive_with_data()
    session_dir = archive.session_dir
    assert session_dir.exists()

    manifest = await archive.close()

    assert manifest is not None
    assert set(manifest.keys()) == {"candles", "strategy_events", "session_metadata"}
    assert manifest["candles"].endswith("candles.parquet")
    assert manifest["strategy_events"].endswith("strategy_events.msgpack")
    assert manifest["session_metadata"].endswith("session.json")
    # Every manifest key was actually uploaded.
    assert set(manifest.values()) <= set(fake.uploaded.keys())
    # Local workspace is gone only after every upload verified.
    assert not session_dir.exists()


@pytest.mark.asyncio
async def test_close_keeps_local_workspace_on_upload_failure(monkeypatch):
    archive = await _make_archive_with_data(session_id="sess-fail-upload")
    session_dir = archive.session_dir

    # Discover the real key so we can target the failure precisely.
    from app.utils.artifact_paths import ArtifactPaths

    paths = ArtifactPaths(strategy_id="strat-1", run_id="sess-fail-upload", kind="live-sessions")
    fake = _FakeStorageService(fail_keys={paths.live_events})
    _patch_storage_service(monkeypatch, fake)

    manifest = await archive.close()

    assert manifest is None
    assert session_dir.exists()
    assert archive.candles_path.exists()
    assert archive.events_path.exists()
    assert archive.metadata_path.exists()


@pytest.mark.asyncio
async def test_close_keeps_local_workspace_on_verify_failure(monkeypatch):
    archive = await _make_archive_with_data(session_id="sess-fail-verify")
    session_dir = archive.session_dir

    from app.utils.artifact_paths import ArtifactPaths

    paths = ArtifactPaths(strategy_id="strat-1", run_id="sess-fail-verify", kind="live-sessions")
    fake = _FakeStorageService(verify_fail_keys={paths.live_candles})
    _patch_storage_service(monkeypatch, fake)

    manifest = await archive.close()

    assert manifest is None
    assert session_dir.exists()


@pytest.mark.asyncio
async def test_close_is_idempotent(monkeypatch):
    fake = _FakeStorageService()
    _patch_storage_service(monkeypatch, fake)

    archive = await _make_archive_with_data(session_id="sess-idempotent")
    first = await archive.close()
    assert first is not None

    upload_count_after_first_close = len(fake.uploaded)
    second = await archive.close()

    assert second is None
    assert len(fake.uploaded) == upload_count_after_first_close


@pytest.mark.asyncio
async def test_close_with_no_local_files_returns_empty_manifest(monkeypatch):
    fake = _FakeStorageService()
    _patch_storage_service(monkeypatch, fake)

    # Only session.json is ever created eagerly at construction time; no
    # candle/event was ever appended.
    archive = SessionWorkspaceArchive("strat-1", "sess-empty")
    manifest = await archive.close()

    assert manifest is not None
    assert "session_metadata" in manifest
    assert "candles" not in manifest
    assert "strategy_events" not in manifest
    assert not archive.session_dir.exists()


@pytest.mark.asyncio
async def test_read_candles_falls_back_to_s3_when_local_missing(monkeypatch):
    fake = _FakeStorageService()
    _patch_storage_service(monkeypatch, fake)

    archive = await _make_archive_with_data(session_id="sess-readback-candles")
    manifest = await archive.close()
    assert manifest is not None

    rows = await SessionWorkspaceArchive.read_candles("sess-readback-candles", manifest)
    assert rows == [[1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 100.0]]


@pytest.mark.asyncio
async def test_read_events_falls_back_to_s3_when_local_missing(monkeypatch):
    fake = _FakeStorageService()
    _patch_storage_service(monkeypatch, fake)

    archive = await _make_archive_with_data(session_id="sess-readback-events")
    manifest = await archive.close()
    assert manifest is not None

    events = await SessionWorkspaceArchive.read_events("sess-readback-events", manifest)
    assert len(events) == 1
    assert events[0]["type"] == "BAR_CLOSED"


@pytest.mark.asyncio
async def test_read_candles_returns_empty_without_local_file_or_manifest():
    assert await SessionWorkspaceArchive.read_candles("sess-never-existed") == []


@pytest.mark.asyncio
async def test_read_events_returns_empty_without_local_file_or_manifest():
    assert await SessionWorkspaceArchive.read_events("sess-never-existed") == []
