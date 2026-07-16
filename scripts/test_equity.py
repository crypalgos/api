import asyncio
import json
from datetime import datetime
from app.celery_app import celery_app
from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.tasks.task_utils import load_and_compile_strategy
from crypalgos_core.engine.simulator import EngineSimulator
from crypalgos_data.exchanges.config import EXCHANGE_REGISTRY
from crypalgos_core.reporting.report_builder import build_analytics_report
from crypalgos_core.reporting.context import AnalyticsContext


async def run_test():
    with open(
        "/Users/ashishjangde/moviees/application/api/scripts/multi_asset_strategy.json",
        "r",
    ) as f:
        strat_json = json.load(f)

    async with AsyncSessionLocal() as session:
        from crypalgos_core.compiler import DAGCompiler

        compiler = DAGCompiler()
        res = compiler.compile(strat_json, "TestStrat")
        code = res.python_code

        # execute code
        namespace = {}
        exec(code, namespace)
        strat_class = namespace["TeststratStrategy"]

        simulator = EngineSimulator(
            exchange_config=EXCHANGE_REGISTRY["delta"](),
            initial_capital=10000.0,
            leverage=1,
            slippage_rate=0.0002,
        )

        start_date = datetime(2026, 1, 1)
        end_date = datetime(2026, 3, 1)

        report = await asyncio.to_thread(
            simulator.run,
            strategy_class=strat_class,
            start_date=start_date,
            end_date=end_date,
        )

        # Analyze equity matches
        snapshots = simulator.strategy.portfolio_engine.snapshots
        for s in snapshots:
            sym_rpnl = sum(s.realized_pnl_by_symbol.values())
            sym_upnl = sum(s.symbol_unrealized_pnl.values())
            expected_eq = 10000.0 + sym_rpnl + sym_upnl
            if abs(s.equity - expected_eq) > 0.01:
                print(
                    f"Mismatch at {s.timestamp}! Equity: {s.equity}, Expected: {expected_eq}"
                )

        print("Done checking snapshots.")


if __name__ == "__main__":
    asyncio.run(run_test())
