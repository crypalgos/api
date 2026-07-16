from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.models.research_run_model import ResearchRun
from app.modules.strategy_service.models.strategy_version_model import StrategyVersion


def validate_strategy_exists(strategy: Strategy | None) -> Strategy:
    """Assert a strategy database record is not None."""
    if not strategy:
        raise ResourceNotFoundException("Strategy not found")
    return strategy


def validate_run_exists(run: ResearchRun | None) -> ResearchRun:
    """Assert a research run database record is not None."""
    if not run:
        raise ResourceNotFoundException("Research run not found")
    return run


def validate_workspace_key(workspace_key: str | None) -> str:
    """Assert the artifact workspace key exists in manifest."""
    if not workspace_key:
        raise ResourceNotFoundException("Run dataset has no workspace key.")
    return workspace_key


def validate_version_exists(version: StrategyVersion | None) -> StrategyVersion:
    """Assert a strategy version snapshot record is not None."""
    if not version:
        raise ResourceNotFoundException("Version not found")
    return version
