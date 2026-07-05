import hashlib
from app.utils.time_utils import now_utc
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from crypalgos_core.compiler import DAGCompiler, compile_dag

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.research_run_model import (
    ResearchRun,
    StrategyLatestResults,
)
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.repositories.research_run_repository import (
    ResearchRunRepository,
)
from app.modules.strategy_service.repositories.strategy_repository import (
    StrategyRepository,
)
from app.modules.strategy_service.schema.strategy_schema import (
    PaginatedResearchRunsResponseSchema,
    PaginatedStrategiesResponseSchema,
    ResearchNoteResponseSchema,
    ResearchRunProgressResponseSchema,
    ResearchRunResponseSchema,
    StrategyResponseSchema,
    StrategyVersionResponseSchema,
    TemplateLibraryItemSchema,
    VersionDiffResponseSchema,
)
from app.modules.strategy_service.services.storage_service import storage_service
from app.modules.strategy_service.services.job_service import JobServiceMixin
from app.modules.strategy_service.services.version_service import VersionServiceMixin
from app.modules.strategy_service.services.data_service import DataServiceMixin
from app.modules.strategy_service.services.live_service import LiveServiceMixin

if not hasattr(DAGCompiler, "compile_dag"):
    DAGCompiler.compile_dag = staticmethod(compile_dag)

logger = logging.getLogger(__name__)


class StrategyService(
    JobServiceMixin, LiveServiceMixin, VersionServiceMixin, DataServiceMixin
):
    def __init__(
        self,
        strategy_repository: StrategyRepository,
        run_repository: Optional[ResearchRunRepository] = None,
    ):
        self.strategy_repository = strategy_repository
        self.run_repository: ResearchRunRepository = run_repository  # type: ignore[assignment]

    async def create_strategy(
        self, user_id: str, name: str, description: str | None, canvas_json: dict
    ) -> tuple[int, StrategyResponseSchema]:
        """Convert a user's visual pipeline configuration into executable python code."""
        compiler = DAGCompiler()
        compile_error = None
        compile_diagnostics = None
        try:
            compiled_script = compiler.compile_dag(canvas_json)
            compile_diagnostics = compiler.last_diagnostics
        except Exception as e:
            compile_error = str(e)
            compile_diagnostics = getattr(e, "diagnostics", None)
            if not compile_diagnostics:
                compile_diagnostics = [
                    {
                        "node_id": None,
                        "node_label": "Compiler",
                        "severity": "ERROR",
                        "error_code": "COMPILATION_ERROR",
                        "message": compile_error,
                        "suggestions": [],
                    }
                ]
            compiled_script = f"# Compilation failed during strategy creation.\n# Error: {compile_error}\n"

        strategy = Strategy(
            user_id=user_id,
            name=name,
            description=description,
            canvas_json=canvas_json,
            compiled_code=compiled_script,
            is_code_modified=False,
            is_template=False,
            is_archived=False,
            strategy_type="VISUAL",
            source_code=None,
            compiled_hash=(
                hashlib.sha256(compiled_script.encode("utf-8")).hexdigest()
                if isinstance(compiled_script, str)
                else "mock_hash"
            ),
            current_version=0,
            has_unpublished_changes=True,
        )
        created_strategy = await self.strategy_repository.create(strategy)
        response = StrategyResponseSchema.model_validate(created_strategy)
        response.compile_error = compile_error
        response.compile_diagnostics = compile_diagnostics
        return 201, response

    async def save_custom_code(
        self, user_id: str, strategy_id: str, code: str
    ) -> tuple[int, StrategyResponseSchema]:
        """Directly overwrite strategy python script inside Monaco editor."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        strategy.compiled_code = code
        strategy.source_code = code
        strategy.is_code_modified = True
        strategy.strategy_type = "CODE"
        strategy.has_unpublished_changes = True
        strategy.compiled_hash = (
            hashlib.sha256(code.encode("utf-8")).hexdigest()
            if isinstance(code, str)
            else "mock_hash"
        )
        strategy.updated_at = now_utc()  # type: ignore[assignment]

        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)

    save_strategy_code = save_custom_code

    async def get_strategy(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, StrategyResponseSchema]:
        """Retrieve a specific visual strategy layout."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.modules.strategy_service.models.research_run_model import (
            StrategyLatestResults,
        )

        stmt = (
            select(Strategy)
            .where(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .options(
                selectinload(Strategy.latest_results).selectinload(
                    StrategyLatestResults.latest_backtest
                )
            )
        )
        res = await self.strategy_repository.session.execute(stmt)
        strategy = res.scalar_one_or_none()

        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        resp = StrategyResponseSchema.model_validate(strategy)

        # Populate counts for single strategy
        from sqlalchemy import func

        count_stmt = (
            select(ResearchRun.run_type, func.count(ResearchRun.id))
            .where(ResearchRun.strategy_id == strategy_id)
            .group_by(ResearchRun.run_type)
        )
        count_res = await self.strategy_repository.session.execute(count_stmt)

        counts = {
            "backtests": 0,
            "montecarlos": 0,
            "walkforwards": 0,
            "optimizations": 0,
        }
        for r_type, cnt in count_res:
            type_key = f"{r_type.lower()}s"
            # Map optimization -> optimizations
            if type_key == "optimizations":
                type_key = "optimizations"
            elif type_key == "montecarlos":
                type_key = "montecarlos"
            elif type_key == "walkforwards":
                type_key = "walkforwards"
            elif type_key == "backtests":
                type_key = "backtests"

            if type_key in counts:
                counts[type_key] = cnt
        resp.research_counts = counts

        # Populate is_golden
        from app.modules.strategy_service.models.strategy_version_model import (
            StrategyVersion,
        )

        golden_stmt = select(StrategyVersion.id).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.is_golden == True,
        )
        golden_res = await self.strategy_repository.session.execute(golden_stmt)
        resp.is_golden = golden_res.scalar() is not None

        # Populate latest_metrics and equity_preview
        latest_backtest = (
            strategy.latest_results.latest_backtest if strategy.latest_results else None
        )
        if latest_backtest and latest_backtest.summary_json:
            sum_json = latest_backtest.summary_json
            resp.latest_metrics = {
                "return_pct": sum_json.get("total_return_pct", 0.0),
                "sharpe": sum_json.get("sharpe_ratio"),
                "drawdown": sum_json.get("max_drawdown_pct", 0.0),
            }
            resp.equity_preview = sum_json.get("equity_preview")
        else:
            resp.latest_metrics = None
            resp.equity_preview = None

        return 200, resp

    async def list_strategies(
        self,
        user_id: str,
        page: int = 1,
        limit: int = 8,
        search: str = "",
        is_template: Optional[bool] = None,
        archived: bool = False,
    ) -> tuple[int, PaginatedStrategiesResponseSchema]:
        """Retrieve paginated summary list of user strategies."""
        paginated_data = await self.strategy_repository.get_strategies_paginated(
            user_id, page, limit, search, archived=archived
        )

        # Filter templates if requested
        items = paginated_data["strategies"]
        if is_template is not None:
            items = [s for s in items if s.is_template == is_template]

        strategy_ids = [s.id for s in items]
        research_counts_map = {}
        golden_versions_map = {}

        if strategy_ids:
            from sqlalchemy import select, func

            # Query counts
            count_stmt = (
                select(
                    ResearchRun.strategy_id,
                    ResearchRun.run_type,
                    func.count(ResearchRun.id),
                )
                .where(ResearchRun.strategy_id.in_(strategy_ids))
                .group_by(ResearchRun.strategy_id, ResearchRun.run_type)
            )
            count_res = await self.strategy_repository.session.execute(count_stmt)
            for strat_id, r_type, cnt in count_res:
                if strat_id not in research_counts_map:
                    research_counts_map[strat_id] = {
                        "backtests": 0,
                        "montecarlos": 0,
                        "walkforwards": 0,
                        "optimizations": 0,
                    }

                type_key = f"{r_type.lower()}s"  # BACKTEST -> backtests
                if type_key == "optimizations":
                    type_key = "optimizations"
                elif type_key == "montecarlos":
                    type_key = "montecarlos"
                elif type_key == "walkforwards":
                    type_key = "walkforwards"
                elif type_key == "backtests":
                    type_key = "backtests"

                if type_key in research_counts_map[strat_id]:
                    research_counts_map[strat_id][type_key] = cnt

            # Check golden versions
            from app.modules.strategy_service.models.strategy_version_model import (
                StrategyVersion,
            )

            golden_stmt = select(StrategyVersion.strategy_id).where(
                StrategyVersion.strategy_id.in_(strategy_ids),
                StrategyVersion.is_golden == True,
            )
            golden_res = await self.strategy_repository.session.execute(golden_stmt)
            for row in golden_res:
                golden_versions_map[row[0]] = True

        response_strategies = []
        for s in items:
            resp = StrategyResponseSchema.model_validate(s)

            # Set is_golden
            resp.is_golden = golden_versions_map.get(s.id, False)

            # Set research_counts
            resp.research_counts = research_counts_map.get(
                s.id,
                {
                    "backtests": 0,
                    "montecarlos": 0,
                    "walkforwards": 0,
                    "optimizations": 0,
                },
            )

            # Set latest_metrics & equity_preview
            latest_backtest = (
                s.latest_results.latest_backtest if s.latest_results else None
            )
            if latest_backtest and latest_backtest.summary_json:
                sum_json = latest_backtest.summary_json
                resp.latest_metrics = {
                    "return_pct": sum_json.get("total_return_pct", 0.0),
                    "sharpe": sum_json.get("sharpe_ratio"),
                    "drawdown": sum_json.get("max_drawdown_pct", 0.0),
                }
                resp.equity_preview = sum_json.get("equity_preview")
            else:
                resp.latest_metrics = None
                resp.equity_preview = None

            response_strategies.append(resp)

        paginated_data["strategies"] = response_strategies
        paginated_data["total"] = len(response_strategies)
        return 200, PaginatedStrategiesResponseSchema.model_validate(paginated_data)

    async def update_canvas(
        self,
        user_id: str,
        strategy_id: str,
        canvas_json: dict,
        name: str | None = None,
        description: str | None = None,
    ) -> tuple[int, StrategyResponseSchema]:
        """Save visual canvas node/edge graph and recompile to Python strategy code."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        compiler = DAGCompiler()
        compile_error = None
        compile_diagnostics = None
        try:
            compiled_script = compiler.compile_dag(canvas_json)
            compile_diagnostics = compiler.last_diagnostics
        except Exception as e:
            compile_error = str(e)
            compile_diagnostics = getattr(e, "diagnostics", None)
            if not compile_diagnostics:
                compile_diagnostics = [
                    {
                        "node_id": None,
                        "node_label": "Compiler",
                        "severity": "ERROR",
                        "error_code": "COMPILATION_ERROR",
                        "message": compile_error,
                        "suggestions": [],
                    }
                ]
            compiled_script = strategy.compiled_code

        strategy.canvas_json = canvas_json
        strategy.compiled_code = compiled_script
        strategy.is_code_modified = False
        strategy.strategy_type = "VISUAL"
        strategy.has_unpublished_changes = True
        strategy.compiled_hash = (
            hashlib.sha256(compiled_script.encode("utf-8")).hexdigest()
            if isinstance(compiled_script, str)
            else "mock_hash"
        )
        strategy.updated_at = now_utc()  # type: ignore[assignment]
        if name is not None:
            strategy.name = name
        if description is not None:
            strategy.description = description

        updated_strategy = await self.strategy_repository.update(strategy.id)
        response = StrategyResponseSchema.model_validate(updated_strategy)
        response.compile_error = compile_error
        response.compile_diagnostics = compile_diagnostics
        return 200, response

    async def reset_to_visual_builder(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, StrategyResponseSchema]:
        """Reset custom code edits by recompiling from the saved Visual Canvas graph."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        compiler = DAGCompiler()
        compiled_script = compiler.compile_dag(strategy.canvas_json)

        strategy.compiled_code = compiled_script
        strategy.is_code_modified = False
        strategy.strategy_type = "VISUAL"
        strategy.has_unpublished_changes = True
        strategy.compiled_hash = (
            hashlib.sha256(compiled_script.encode("utf-8")).hexdigest()
            if isinstance(compiled_script, str)
            else "mock_hash"
        )
        strategy.updated_at = now_utc()  # type: ignore[assignment]

        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)

    async def delete_strategy(self, user_id: str, strategy_id: str) -> tuple[int, dict]:
        """Soft delete if active, or permanently hard delete (cleaning S3/DB) if already archived."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        if strategy.is_archived:
            from sqlalchemy import delete

            # 1. Clean up S3 prefix / files
            await storage_service.delete_directory(f"reports/{strategy_id}")

            # 2. Delete associated research runs from database
            await self.strategy_repository.session.execute(
                delete(ResearchRun).where(ResearchRun.strategy_id == strategy_id)
            )

            # 3. Delete latest results mapping
            await self.strategy_repository.session.execute(
                delete(StrategyLatestResults).where(
                    StrategyLatestResults.strategy_id == strategy_id
                )
            )

            # 4. Hard delete the strategy row
            await self.strategy_repository.session.execute(
                delete(Strategy).where(Strategy.id == strategy_id)
            )
            await self.strategy_repository.session.commit()

            return 200, {
                "success": True,
                "message": "Strategy and all associated history permanently deleted.",
            }

        strategy.is_archived = True
        strategy.updated_at = now_utc()  # type: ignore[assignment]
        await self.strategy_repository.update(strategy.id)
        return 200, {"success": True, "message": "Strategy archived successfully."}

    async def restore_strategy(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, dict]:
        """Restore/unarchive a strategy from soft delete."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        if not strategy.is_archived:
            return 200, StrategyResponseSchema.model_validate(strategy).model_dump()

        strategy.is_archived = False
        strategy.updated_at = now_utc()  # type: ignore[assignment]
        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy).model_dump()
