"""Tests for background strategy backtesting tasks."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.tasks.backtest_tasks import _execute_backtest_internal
from app.modules.strategy_service.tasks.ast_validator import validate_strategy_ast


from app.modules.strategy_service.models.research_run_model import ResearchRun

@pytest.mark.asyncio
@patch("app.modules.strategy_service.tasks.backtest_tasks.settings.sandbox_enabled", False)
@patch("crypalgos_core.database.load_candles_from_clickhouse")
@patch("app.modules.strategy_service.tasks.backtest_tasks.EngineSimulator")
@patch("app.modules.strategy_service.tasks.task_utils.AsyncSessionLocal")
@patch("app.modules.strategy_service.tasks.backtest_tasks.AsyncSessionLocal")
@patch("app.modules.strategy_service.tasks.backtest_tasks.storage_service")
async def test_run_asynchronous_backtest_task_success(
    mock_storage: MagicMock,
    mock_db_session_cls_bt: MagicMock,
    mock_db_session_cls_tu: MagicMock,
    mock_simulator_cls: MagicMock,
    mock_load_candles: MagicMock,
    sample_strategy: Strategy
) -> None:
    """Test successful asynchronous backtest execution from end to end."""
    import numpy as np
    mock_load_candles.return_value = np.array([
        [1779882900000.0, 60000.0, 60100.0, 59900.0, 60050.0, 100.0]
    ])
    # 1. Setup Mock DB session
    mock_storage.upload_payload = AsyncMock()
    mock_storage.upload_raw_payload = AsyncMock()
    mock_session = AsyncMock()
    
    def get_side_effect(model_class, model_id):
        if model_class == Strategy:
            return sample_strategy
        elif model_class == ResearchRun:
            return ResearchRun(id=model_id, strategy_id="strat-123", type="BACKTEST", status="RUNNING")
        return None
    mock_session.get.side_effect = get_side_effect
    
    mock_execute_res = MagicMock()
    mock_execute_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_execute_res

    # Configure session.begin() to support async context manager interface
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock()
    mock_session.begin.return_value.__aexit__ = AsyncMock()
    
    # Configure the 'async with AsyncSessionLocal()' context manager mock
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_db_session_cls_bt.return_value = mock_session_ctx
    mock_db_session_cls_tu.return_value = mock_session_ctx

    # 2. Setup Mock EngineSimulator
    mock_simulator = MagicMock()
    mock_report = {
        "metrics": {
            "global": {
                "net_profit": 500.0,
                "win_rate": 0.75,
                "profit_factor": 2.0,
                "sharpe_ratio": 2.5,
                "max_drawdown_pct": 2.0
            }
        },
        "datasets": {
            "global_equity_curve": [[12345678, 10000.0], [12345679, 10500.0]]
        },
        "trades": {"recent_trades": [{"id": 1, "symbol": "BTC/USDT", "side": "buy"}]},
        "monthly": {},
        "correlations": {}
    }
    mock_simulator.run.return_value = mock_report
    mock_simulator_cls.return_value = mock_simulator

    # 3. Trigger the internal backtest logic directly using await
    result = await _execute_backtest_internal(
        backtest_id="test-bt-123",
        strategy_id="strat-123",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
        initial_capital=10000.0
    )

    # 4. Verify outputs and side effects
    assert result["success"] is True
    assert "backtest_id" in result
    assert result["summary"]["net_profit"] == 500.0
    assert result["summary"]["win_rate"] == 0.75

    # Verify database calls
    assert mock_session.get.call_count >= 2

    # Verify simulation params
    assert mock_simulator_cls.call_count == 1
    call_kwargs = mock_simulator_cls.call_args.kwargs
    assert call_kwargs.get("initial_capital") == 10000.0
    assert call_kwargs.get("slippage_rate") == 0.0002
    mock_simulator.run.assert_called_once()


def test_ast_screening_valid_strategy() -> None:
    """Test that a valid strategy passes AST pre-screening."""
    from app.modules.strategy_service.tasks.ast_validator import validate_strategy_ast
    
    code = """import numpy as np
from crypalgos_core.runtime.strategy_base import StrategyBase

class SimpleTrendStrategy(StrategyBase):
    def initialize(self) -> None:
        self.leverage = 2
        
    def on_data(self, data) -> None:
        if data.btc.close > 50000:
            self.buy("BTCUSDT", amount=0.1)
"""
    assert validate_strategy_ast(code) is True


def test_ast_screening_forbidden_imports() -> None:
    """Test that strategies with forbidden imports are rejected."""
    from app.modules.strategy_service.tasks.ast_validator import validate_strategy_ast
    
    code_with_os = """import os
from crypalgos_core.runtime.strategy_base import StrategyBase

class Exploit(StrategyBase):
    def initialize(self) -> None:
        os.system("rm -rf /")
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_os)
    assert "Import of 'os' is strictly forbidden." in str(exc_info.value)

    code_with_sys_from = """from sys import modules
from crypalgos_core.runtime.strategy_base import StrategyBase

class Exploit(StrategyBase):
    pass
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_sys_from)
    assert "Import from 'sys' is strictly forbidden." in str(exc_info.value)


def test_ast_screening_forbidden_calls() -> None:
    """Test that strategies with forbidden function calls are rejected."""
    from app.modules.strategy_service.tasks.ast_validator import validate_strategy_ast
    
    code_with_eval = """from crypalgos_core.runtime.strategy_base import StrategyBase

class Exploit(StrategyBase):
    def on_data(self, data) -> None:
        eval("__import__('os').system('ls')")
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_eval)
    assert "Calling built-in function 'eval()' is strictly forbidden." in str(exc_info.value)


def test_ast_screening_dunder_attacks() -> None:
    """Test that strategies with double underscore attribute accesses are rejected."""
    from app.modules.strategy_service.tasks.ast_validator import validate_strategy_ast
    
    code_with_dunder = """from crypalgos_core.runtime.strategy_base import StrategyBase

class Exploit(StrategyBase):
    def on_data(self, data) -> None:
        c = self.__class__.__base__
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_dunder)
    assert "Access to private attribute" in str(exc_info.value)
    assert "is strictly forbidden." in str(exc_info.value)


@pytest.mark.asyncio
@patch("app.modules.strategy_service.tasks.task_utils.AsyncSessionLocal")
@patch("app.modules.strategy_service.tasks.backtest_tasks.AsyncSessionLocal")
async def test_run_asynchronous_backtest_ast_validation_failure(
    mock_db_session_cls_bt: MagicMock,
    mock_db_session_cls_tu: MagicMock,
    sample_strategy: Strategy
) -> None:
    """Test that asynchronous backtest execution fails if AST validation fails."""
    # Setup Strategy with malicious code
    sample_strategy.compiled_code = """import os
class MaliciousStrategy:
    pass
"""
    
    mock_session = AsyncMock()
    mock_session.get.return_value = sample_strategy
    
    mock_execute_res = MagicMock()
    mock_execute_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_execute_res

    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock()
    mock_session.begin.return_value.__aexit__ = AsyncMock()
    
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_db_session_cls_bt.return_value = mock_session_ctx
    mock_db_session_cls_tu.return_value = mock_session_ctx

    # Calling the executor with malicious strategy should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await _execute_backtest_internal(
            backtest_id="test-bt-123",
            strategy_id="strat-123",
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 2),
            initial_capital=10000.0
        )
    
    assert "Import of 'os' is strictly forbidden." in str(exc_info.value)
    
    # Verify the database load succeeded but no simulator was run
    assert mock_session.get.call_count >= 2
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
@patch("app.modules.strategy_service.tasks.backtest_tasks.settings.sandbox_enabled", False)
@patch("crypalgos_core.database.load_candles_from_clickhouse")
@patch("app.modules.strategy_service.tasks.backtest_tasks.EngineSimulator")
@patch("app.modules.strategy_service.tasks.task_utils.AsyncSessionLocal")
@patch("app.modules.strategy_service.tasks.backtest_tasks.AsyncSessionLocal")
@patch("app.modules.strategy_service.tasks.backtest_tasks.storage_service")
async def test_run_backtest_manifest_validation_failure(
    mock_storage: MagicMock,
    mock_db_session_cls_bt: MagicMock,
    mock_db_session_cls_tu: MagicMock,
    mock_simulator_cls: MagicMock,
    mock_load_candles: MagicMock,
    sample_strategy: Strategy
) -> None:
    """Test that backtest task raises a ValueError if dataset references in report are not in manifest."""
    import numpy as np
    mock_load_candles.return_value = np.array([
        [1779882900000.0, 60000.0, 60100.0, 59900.0, 60050.0, 100.0]
    ])
    mock_storage.upload_payload = AsyncMock()
    mock_storage.upload_raw_payload = AsyncMock()
    mock_session = AsyncMock()
    
    mock_session.get.return_value = sample_strategy
    mock_execute_res = MagicMock()
    mock_execute_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_execute_res

    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock()
    mock_session.begin.return_value.__aexit__ = AsyncMock()
    
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_db_session_cls_bt.return_value = mock_session_ctx
    mock_db_session_cls_tu.return_value = mock_session_ctx

    mock_simulator = MagicMock()
    # Mock report with a dataset reference that doesn't exist in generated_metas/manifest
    mock_report = {
        "metrics": {
            "global": {"net_profit": 500.0, "win_rate": 0.75}
        },
        "report": {
            "datasets": {
                "invalid_reference": {"dataset_id": "non_existent_dataset"}
            }
        },
        "datasets": {},
        "trades": [],
        "monthly": {},
        "correlations": {}
    }
    mock_simulator.run.return_value = mock_report
    mock_simulator_cls.return_value = mock_simulator

    with pytest.raises(ValueError) as exc_info:
        await _execute_backtest_internal(
            backtest_id="test-bt-123",
            strategy_id="strat-123",
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 2),
            initial_capital=10000.0
        )
    assert "Workspace validation failed" in str(exc_info.value)
    assert "non_existent_dataset" in str(exc_info.value)


