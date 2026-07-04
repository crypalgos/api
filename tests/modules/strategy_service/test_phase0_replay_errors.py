"""
Phase 0 — A6: replay must distinguish missing (404) from corrupt (422),
never returning 200 with empty data.
"""
from types import SimpleNamespace

import pytest

from app.exceptions.exceptions import ResourceNotFoundException, ValidationException
from app.modules.replay.services.replay_service import ReplayService


class FakeRunRepo:
    def __init__(self, run=None):
        self._run = run

    async def get_by_id(self, run_id):
        return self._run


class FakeStrategyRepo:
    def __init__(self, strategy=None):
        self._strategy = strategy

    async def get_by_user_and_id(self, user_id, strategy_id):
        return self._strategy


def _service(run=None, strategy=None):
    return ReplayService(FakeStrategyRepo(strategy), FakeRunRepo(run))


def _run(artifact_manifest=None):
    return SimpleNamespace(strategy_id="strat-1", artifact_manifest=artifact_manifest)


@pytest.mark.asyncio
async def test_missing_run_is_404():
    svc = _service(run=None)
    with pytest.raises(ResourceNotFoundException):
        await svc.get_dataset_window("user-1", "run-1", "candles", 0, 10)


@pytest.mark.asyncio
async def test_missing_workspace_key_is_404():
    svc = _service(run=_run(artifact_manifest={}), strategy=object())
    with pytest.raises(ResourceNotFoundException):
        await svc.get_dataset_window("user-1", "run-1", "candles", 0, 10)


@pytest.mark.asyncio
async def test_missing_dataset_is_404_not_200_empty(monkeypatch):
    """The old code swallowed ResourceNotFoundException and returned 200 []."""
    svc = _service(run=_run({"workspace": "s3://key"}), strategy=object())

    class MissingDatasetReader:
        def __init__(self, key):
            pass

        async def get_dataset_bytes(self, name):
            raise ResourceNotFoundException(f"dataset {name} not found")

    monkeypatch.setattr(
        "app.modules.replay.services.replay_service.WorkspaceReader",
        MissingDatasetReader,
    )
    with pytest.raises(ResourceNotFoundException):
        await svc.get_dataset_window("user-1", "run-1", "candles", 0, 10)


@pytest.mark.asyncio
async def test_corrupt_dataset_is_422(monkeypatch):
    svc = _service(run=_run({"workspace": "s3://key"}), strategy=object())

    class CorruptReader:
        def __init__(self, key):
            pass

        async def get_dataset_bytes(self, name):
            return b"not-a-valid-arrow-file"

    monkeypatch.setattr(
        "app.modules.replay.services.replay_service.WorkspaceReader",
        CorruptReader,
    )
    with pytest.raises(ValidationException):
        await svc.get_dataset_window("user-1", "run-1", "candles", 0, 10)


def test_validation_exception_maps_to_422():
    """Global handler must register ValidationException as 422, not fall through to 500."""
    import inspect
    from app.advices import global_exception_handler as geh

    src = inspect.getsource(geh)
    assert "ValidationException" in src
    assert "status_code=422" in src
