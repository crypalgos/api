"""Pins down _recover_one's orphan-detection decision tree (see its own
docstring for the full 4-branch description) with the DB/S3 layers mocked
out -- this is pure orchestration logic, not something that needs a real
database or S3 bucket to verify."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.modules.strategy_service.tasks.live_session_recovery as recovery_mod
from app.modules.strategy_service.tasks.live_session_recovery import _recover_one


def _fake_session(status: str, artifact_manifest=None, strategy_id: str = "strat-1"):
    session = MagicMock()
    session.status = status
    session.artifact_manifest = artifact_manifest
    session.strategy_id = strategy_id
    return session


class _FakeAsyncSessionCtx:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _patch_db(monkeypatch):
    monkeypatch.setattr(
        "app.db.connect_db.AsyncSessionLocal", lambda: _FakeAsyncSessionCtx()
    )


def _patch_repo(monkeypatch, repo_instance):
    monkeypatch.setattr(
        "app.modules.strategy_service.repositories.live_trading_session_repository.LiveTradingSessionRepository",
        lambda session: repo_instance,
    )


@pytest.mark.asyncio
async def test_no_matching_row_leaves_workspace_untouched(monkeypatch, tmp_path):
    monkeypatch.setattr(
        recovery_mod.settings, "live_session_workspace_dir", str(tmp_path)
    )
    _patch_db(monkeypatch)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.reap_if_stale = AsyncMock()
    repo.update_artifact_manifest = AsyncMock()
    _patch_repo(monkeypatch, repo)
    mock_archive_cls = MagicMock()
    monkeypatch.setattr(recovery_mod, "SessionWorkspaceArchive", mock_archive_cls)

    await _recover_one("sess-orphan")

    repo.reap_if_stale.assert_not_awaited()
    mock_archive_cls.assert_not_called()


@pytest.mark.asyncio
async def test_already_archived_deletes_local_copy_without_reupload(monkeypatch, tmp_path):
    session_dir = tmp_path / "sess-archived"
    session_dir.mkdir()
    (session_dir / "candles.parquet").write_bytes(b"stale-local-copy")

    monkeypatch.setattr(
        recovery_mod.settings, "live_session_workspace_dir", str(tmp_path)
    )
    _patch_db(monkeypatch)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(
        return_value=_fake_session("STOPPED", artifact_manifest={"candles": "some/key"})
    )
    repo.reap_if_stale = AsyncMock()
    repo.update_artifact_manifest = AsyncMock()
    _patch_repo(monkeypatch, repo)
    mock_archive_cls = MagicMock()
    monkeypatch.setattr(recovery_mod, "SessionWorkspaceArchive", mock_archive_cls)
    # _session_dir is a real staticmethod on the real class -- keep it real
    # even though the constructor itself is mocked, since _recover_one calls
    # it directly to find the directory to delete.
    from app.modules.strategy_service.services.session_workspace_archive import (
        SessionWorkspaceArchive as RealArchive,
    )
    mock_archive_cls._session_dir = RealArchive._session_dir

    await _recover_one("sess-archived")

    assert not session_dir.exists()
    mock_archive_cls.assert_not_called()  # never constructed -- no re-upload attempted
    repo.update_artifact_manifest.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_session_with_fresh_heartbeat_is_left_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(
        recovery_mod.settings, "live_session_workspace_dir", str(tmp_path)
    )
    _patch_db(monkeypatch)
    running_session = _fake_session("RUNNING", artifact_manifest=None)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=running_session)
    # reap_if_stale returns the session unchanged -- fresh heartbeat, not stale.
    repo.reap_if_stale = AsyncMock(return_value=running_session)
    repo.update_artifact_manifest = AsyncMock()
    _patch_repo(monkeypatch, repo)
    mock_archive_cls = MagicMock()
    monkeypatch.setattr(recovery_mod, "SessionWorkspaceArchive", mock_archive_cls)

    await _recover_one("sess-running")

    repo.reap_if_stale.assert_awaited_once_with(running_session)
    mock_archive_cls.assert_not_called()
    repo.update_artifact_manifest.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_running_session_reaped_to_error_gets_archived(monkeypatch, tmp_path):
    monkeypatch.setattr(
        recovery_mod.settings, "live_session_workspace_dir", str(tmp_path)
    )
    _patch_db(monkeypatch)
    running_session = _fake_session("RUNNING", artifact_manifest=None)
    reaped_session = _fake_session("ERROR", artifact_manifest=None, strategy_id="strat-1")
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=running_session)
    repo.reap_if_stale = AsyncMock(return_value=reaped_session)
    repo.update_artifact_manifest = AsyncMock()
    _patch_repo(monkeypatch, repo)

    mock_archive_instance = MagicMock()
    mock_archive_instance.close = AsyncMock(return_value={"candles": "some/key"})
    mock_archive_cls = MagicMock(return_value=mock_archive_instance)
    monkeypatch.setattr(recovery_mod, "SessionWorkspaceArchive", mock_archive_cls)

    await _recover_one("sess-stale")

    mock_archive_cls.assert_called_once_with("strat-1", "sess-stale")
    mock_archive_instance.close.assert_awaited_once()
    repo.update_artifact_manifest.assert_awaited_once_with("sess-stale", {"candles": "some/key"})


@pytest.mark.asyncio
async def test_stopped_session_is_archived_directly(monkeypatch, tmp_path):
    monkeypatch.setattr(
        recovery_mod.settings, "live_session_workspace_dir", str(tmp_path)
    )
    _patch_db(monkeypatch)
    stopped_session = _fake_session("STOPPED", artifact_manifest=None)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=stopped_session)
    # reap_if_stale is a no-op for already-terminal statuses -- returns as-is.
    repo.reap_if_stale = AsyncMock(return_value=stopped_session)
    repo.update_artifact_manifest = AsyncMock()
    _patch_repo(monkeypatch, repo)

    mock_archive_instance = MagicMock()
    mock_archive_instance.close = AsyncMock(return_value={"candles": "some/key"})
    mock_archive_cls = MagicMock(return_value=mock_archive_instance)
    monkeypatch.setattr(recovery_mod, "SessionWorkspaceArchive", mock_archive_cls)

    await _recover_one("sess-stopped")

    mock_archive_instance.close.assert_awaited_once()
    repo.update_artifact_manifest.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_archive_does_not_persist_manifest(monkeypatch, tmp_path):
    """close() returning None means the upload failed -- must not be
    treated as success, and must not touch the DB manifest column."""
    monkeypatch.setattr(
        recovery_mod.settings, "live_session_workspace_dir", str(tmp_path)
    )
    _patch_db(monkeypatch)
    stopped_session = _fake_session("STOPPED", artifact_manifest=None)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=stopped_session)
    repo.reap_if_stale = AsyncMock(return_value=stopped_session)
    repo.update_artifact_manifest = AsyncMock()
    _patch_repo(monkeypatch, repo)

    mock_archive_instance = MagicMock()
    mock_archive_instance.close = AsyncMock(return_value=None)
    mock_archive_cls = MagicMock(return_value=mock_archive_instance)
    monkeypatch.setattr(recovery_mod, "SessionWorkspaceArchive", mock_archive_cls)

    await _recover_one("sess-fails-to-archive")

    mock_archive_instance.close.assert_awaited_once()
    repo.update_artifact_manifest.assert_not_awaited()
