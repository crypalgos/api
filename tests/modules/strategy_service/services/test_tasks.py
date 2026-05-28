"""Tests for background strategy backtesting tasks."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.tasks import _execute_backtest_internal


@pytest.mark.asyncio
@patch("app.modules.strategy_service.tasks.settings.sandbox_enabled", False)
@patch("crypalgos_core.database.load_candles_from_clickhouse")
@patch("app.modules.strategy_service.tasks.EngineSimulator")
@patch("app.modules.strategy_service.tasks.AsyncSessionLocal")
async def test_run_asynchronous_backtest_task_success(
    mock_db_session_cls: MagicMock,
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
    mock_session = AsyncMock()
    mock_session.get.return_value = sample_strategy
    
    # Configure session.begin() to support async context manager interface
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock()
    mock_session.begin.return_value.__aexit__ = AsyncMock()
    
    # Configure the 'async with AsyncSessionLocal()' context manager mock
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_db_session_cls.return_value = mock_session_ctx

    # 2. Setup Mock EngineSimulator
    mock_simulator = MagicMock()
    mock_report = {
        "net_profit": 500.0,
        "win_rate": 0.75,
        "profit_factor": 2.0,
        "sharpe_ratio": 2.5,
        "max_drawdown": 0.02,
        "final_balance": 10500.0,
        "trades": [{"id": 1, "symbol": "BTC/USDT", "side": "buy"}],
        "equity_curve": [[12345678, 10000.0], [12345679, 10500.0]],
        "drawdown_curve": [[12345678, 0.0], [12345679, 0.0]]
    }
    mock_simulator.run.return_value = mock_report
    mock_simulator_cls.return_value = mock_simulator

    # 3. Trigger the internal backtest logic directly using await
    result = await _execute_backtest_internal(
        strategy_id="strat-123",
        exchange="binance",
        symbol="BTC/USDT",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
        initial_capital=10000.0,
        leverage=1
    )

    # 4. Verify outputs and side effects
    assert result["success"] is True
    assert "backtest_id" in result
    assert result["metrics"]["net_profit"] == 500.0
    assert result["metrics"]["win_rate"] == 0.75

    # Verify database calls
    mock_session.get.assert_called_once_with(Strategy, "strat-123")
    mock_session.add.assert_called_once()
    
    # Extract the saved Backtest instance and verify its properties
    saved_backtest = mock_session.add.call_args[0][0]
    assert saved_backtest.strategy_id == "strat-123"
    assert saved_backtest.exchange == "binance"
    assert saved_backtest.symbol == "BTC/USDT"
    
    # Assert metrics_json structure and values
    assert saved_backtest.metrics_json["net_profit"] == 500.0
    assert saved_backtest.metrics_json["win_rate"] == 0.75
    assert saved_backtest.metrics_json["profit_factor"] == 2.0
    assert saved_backtest.metrics_json["sharpe_ratio"] == 2.5
    
    # Assert charting_json structure and values
    assert len(saved_backtest.charting_json["trades"]) == 1
    assert saved_backtest.charting_json["trades"][0]["symbol"] == "BTC/USDT"
    assert saved_backtest.charting_json["trades"][0]["side"] == "buy"
    assert len(saved_backtest.charting_json["equity_curve"]) > 0
    assert len(saved_backtest.charting_json["drawdown_curve"]) > 0
    
    mock_session.flush.assert_called_once()
    mock_session.refresh.assert_called_once()

    # Verify simulation params
    mock_simulator_cls.assert_called_once_with(
        initial_capital=10000.0,
        leverage=1,
        slippage_rate=0.0002,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0004
    )
    mock_simulator.run.assert_called_once()


def test_ast_screening_valid_strategy() -> None:
    """Test that a valid strategy passes AST pre-screening."""
    from app.modules.strategy_service.tasks import validate_strategy_ast
    
    code = """import numpy as np
from crypalgos_core.strategy import StrategyBase

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
    from app.modules.strategy_service.tasks import validate_strategy_ast
    
    code_with_os = """import os
from crypalgos_core.strategy import StrategyBase

class Exploit(StrategyBase):
    def initialize(self) -> None:
        os.system("rm -rf /")
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_os)
    assert "Import of 'os' is strictly forbidden." in str(exc_info.value)

    code_with_sys_from = """from sys import modules
from crypalgos_core.strategy import StrategyBase

class Exploit(StrategyBase):
    pass
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_sys_from)
    assert "Import from 'sys' is strictly forbidden." in str(exc_info.value)


def test_ast_screening_forbidden_calls() -> None:
    """Test that strategies with forbidden function calls are rejected."""
    from app.modules.strategy_service.tasks import validate_strategy_ast
    
    code_with_eval = """from crypalgos_core.strategy import StrategyBase

class Exploit(StrategyBase):
    def on_data(self, data) -> None:
        eval("__import__('os').system('ls')")
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_eval)
    assert "Calling built-in function 'eval()' is strictly forbidden." in str(exc_info.value)


def test_ast_screening_dunder_attacks() -> None:
    """Test that strategies with double underscore attribute accesses are rejected."""
    from app.modules.strategy_service.tasks import validate_strategy_ast
    
    code_with_dunder = """from crypalgos_core.strategy import StrategyBase

class Exploit(StrategyBase):
    def on_data(self, data) -> None:
        c = self.__class__.__base__
"""
    with pytest.raises(ValueError) as exc_info:
        validate_strategy_ast(code_with_dunder)
    assert "Access to private attribute" in str(exc_info.value)
    assert "is strictly forbidden." in str(exc_info.value)


@pytest.mark.asyncio
@patch("app.modules.strategy_service.tasks.AsyncSessionLocal")
async def test_run_asynchronous_backtest_ast_validation_failure(
    mock_db_session_cls: MagicMock,
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
    
    mock_session.begin = MagicMock()
    mock_session.begin.return_value.__aenter__ = AsyncMock()
    mock_session.begin.return_value.__aexit__ = AsyncMock()
    
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_db_session_cls.return_value = mock_session_ctx

    # Calling the executor with malicious strategy should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await _execute_backtest_internal(
            strategy_id="strat-123",
            exchange="binance",
            symbol="BTC/USDT",
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 2),
            initial_capital=10000.0,
            leverage=1
        )
    
    assert "Import of 'os' is strictly forbidden." in str(exc_info.value)
    
    # Verify the database load succeeded but no simulator was run
    mock_session.get.assert_called_once_with(Strategy, "strat-123")
    mock_session.add.assert_not_called()

