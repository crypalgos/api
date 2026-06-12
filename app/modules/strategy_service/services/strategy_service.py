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
    ResearchRunProgressResponseSchema,
    ResearchRunResponseSchema,
    StrategyResponseSchema,
    TemplateLibraryItemSchema,
)
from app.modules.strategy_service.services.storage_service import storage_service

if not hasattr(DAGCompiler, "compile_dag"):
    DAGCompiler.compile_dag = staticmethod(compile_dag)

logger = logging.getLogger(__name__)


class StrategyService:
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
                compile_diagnostics = [{
                    "node_id": None,
                    "node_label": "Compiler",
                    "severity": "ERROR",
                    "error_code": "COMPILATION_ERROR",
                    "message": compile_error,
                    "suggestions": []
                }]
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
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
            
        strategy.compiled_code = code
        strategy.is_code_modified = True
        strategy.updated_at = datetime.utcnow()  # type: ignore[assignment]
        
        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)

    save_strategy_code = save_custom_code
        
    async def get_strategy(self, user_id: str, strategy_id: str) -> tuple[int, StrategyResponseSchema]:
        """Retrieve a specific visual strategy layout."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")
        return 200, StrategyResponseSchema.model_validate(strategy)

    async def list_strategies(
        self, user_id: str, page: int = 1, limit: int = 8, search: str = "", is_template: Optional[bool] = None
    ) -> tuple[int, PaginatedStrategiesResponseSchema]:
        """Retrieve paginated summary list of user strategies, excluding archived ones."""
        paginated_data = await self.strategy_repository.get_strategies_paginated(user_id, page, limit, search)
        
        # Filter templates if requested, and filter out archived ones
        items = [s for s in paginated_data["strategies"] if not s.is_archived]
        if is_template is not None:
            items = [s for s in items if s.is_template == is_template]

        paginated_data["strategies"] = items
        paginated_data["total"] = len(items)
        return 200, PaginatedStrategiesResponseSchema.model_validate(paginated_data)

    async def update_canvas(
        self, user_id: str, strategy_id: str, canvas_json: dict, name: str | None = None, description: str | None = None
    ) -> tuple[int, StrategyResponseSchema]:
        """Save visual canvas node/edge graph and recompile to Python strategy code."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
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
                compile_diagnostics = [{
                    "node_id": None,
                    "node_label": "Compiler",
                    "severity": "ERROR",
                    "error_code": "COMPILATION_ERROR",
                    "message": compile_error,
                    "suggestions": []
                }]
            compiled_script = strategy.compiled_code

        strategy.canvas_json = canvas_json
        strategy.compiled_code = compiled_script
        strategy.is_code_modified = False
        strategy.updated_at = datetime.utcnow()  # type: ignore[assignment]
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
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")
            
        compiler = DAGCompiler()
        compiled_script = compiler.compile_dag(strategy.canvas_json)
        
        strategy.compiled_code = compiled_script
        strategy.is_code_modified = False
        strategy.updated_at = datetime.utcnow()  # type: ignore[assignment]
        
        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)

    async def delete_strategy(self, user_id: str, strategy_id: str) -> tuple[int, dict]:
        """Soft delete if active, or permanently hard delete (cleaning S3/DB) if already archived."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
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
                delete(StrategyLatestResults).where(StrategyLatestResults.strategy_id == strategy_id)
            )
            
            # 4. Hard delete the strategy row
            await self.strategy_repository.session.execute(
                delete(Strategy).where(Strategy.id == strategy_id)
            )
            await self.strategy_repository.session.commit()
            
            return 200, {"success": True, "message": "Strategy and all associated history permanently deleted."}
            
        strategy.is_archived = True
        strategy.updated_at = datetime.utcnow()  # type: ignore[assignment]
        await self.strategy_repository.update(strategy.id)
        return 200, {"success": True, "message": "Strategy archived successfully."}

    # ─── Research Runs Methods ──────────────────────────────────────────────────

    async def trigger_backtest(
        self, user_id: str, strategy_id: str, start_date: datetime, end_date: datetime, initial_capital: float
    ) -> tuple[int, dict]:
        """Submit a single backtest job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_asynchronous_backtest_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        run = ResearchRun(
            strategy_id=strategy_id,
            type="BACKTEST",
            name=f"Backtest {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            status="PENDING",
            progress_percent=0,
            summary_json={},
        )
        created_run = await self.run_repository.create(run)

        task = run_asynchronous_backtest_task.delay(
            backtest_id=created_run.id,
            strategy_id=strategy_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": "PENDING",
            "message": "Backtest enqueued successfully."
        }

    async def trigger_optimization(
        self, user_id: str, strategy_id: str, start_date: datetime, end_date: datetime, initial_capital: float,
        parameter_space: list, constraints: list, objective: str, search_type: str, max_runs: int
    ) -> tuple[int, dict]:
        """Submit an optimization job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_optimization_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        run = ResearchRun(
            strategy_id=strategy_id,
            type="OPTIMIZATION",
            name=f"Optimization {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            status="PENDING",
            progress_percent=0,
            summary_json={},
        )
        created_run = await self.run_repository.create(run)

        task = run_optimization_task.delay(
            run_id=created_run.id,
            strategy_id=strategy_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital,
            parameter_space_json=parameter_space,
            constraints_json=constraints,
            objective=objective,
            search_type=search_type,
            max_runs=max_runs,
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": "PENDING",
            "message": "Optimization enqueued successfully."
        }

    async def trigger_walkforward(
        self, user_id: str, strategy_id: str, start_date: datetime, end_date: datetime, initial_capital: float,
        train_period_months: int, test_period_months: int, step_months: int, objective: str,
        parameter_space: list, constraints: list, window_type: str
    ) -> tuple[int, dict]:
        """Submit a walkforward validation job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_walkforward_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        window_config = {
            "train_period_months": train_period_months,
            "test_period_months": test_period_months,
            "step_months": step_months,
            "parameter_space": parameter_space,
            "constraints": constraints,
            "window_type": window_type,
        }

        run = ResearchRun(
            strategy_id=strategy_id,
            type="WALKFORWARD",
            name=f"WalkForward {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            status="PENDING",
            progress_percent=0,
            summary_json={},
        )
        created_run = await self.run_repository.create(run)

        task = run_walkforward_task.delay(
            run_id=created_run.id,
            strategy_id=strategy_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            initial_capital=initial_capital,
            window_config_json=window_config,
            objective=objective,
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": "PENDING",
            "message": "WalkForward enqueued successfully."
        }

    async def trigger_montecarlo(
        self, user_id: str, strategy_id: str, source_backtest_id: str, simulation_count: int,
        method: str, random_seed: Optional[int]
    ) -> tuple[int, dict]:
        """Submit a Monte Carlo simulation job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_montecarlo_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        run = ResearchRun(
            strategy_id=strategy_id,
            type="MONTECARLO",
            name=f"Monte Carlo {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            status="PENDING",
            progress_percent=0,
            summary_json={},
        )
        created_run = await self.run_repository.create(run)

        task = run_montecarlo_task.delay(
            run_id=created_run.id,
            strategy_id=strategy_id,
            source_backtest_id=source_backtest_id,
            simulation_count=simulation_count,
            method=method,
            random_seed=random_seed,
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": "PENDING",
            "message": "Monte Carlo enqueued successfully."
        }

    async def list_runs(
        self, user_id: str, strategy_id: str, run_type: Optional[str] = None, status: Optional[str] = None,
        is_favorite: Optional[bool] = None, sort_by: str = "updated_at", page: int = 1, limit: int = 8
    ) -> tuple[int, PaginatedResearchRunsResponseSchema]:
        """Get paginated history of research runs, sorted and filtered."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        paginated = await self.run_repository.get_runs_paginated(
            strategy_id=strategy_id, run_type=run_type, status=status,
            is_favorite=is_favorite, sort_by=sort_by, page=page, limit=limit
        )

        return 200, PaginatedResearchRunsResponseSchema.model_validate(paginated)

    async def get_run(
        self, user_id: str, strategy_id: str, run_id: str
    ) -> tuple[int, Dict[str, Any]]:
        """Fetch details of a single run, downloading reports and metadata from storage."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run = await self.run_repository.get_by_id(run_id)
        if not run or run.strategy_id != strategy_id:
            raise ResourceNotFoundException("Research run not found")

        metadata = {}
        report = {}

        if run.metadata_s3_key:
            try:
                metadata = await storage_service.download_payload(run.metadata_s3_key)
            except Exception as e:
                logger.error(f"Failed to download run metadata: {e}")

        if run.report_s3_key:
            try:
                report = await storage_service.download_payload(run.report_s3_key)
            except Exception as e:
                logger.error(f"Failed to download run report: {e}")

        return 200, {
            "metadata": metadata,
            "report": report,
            "id": run.id,
            "status": run.status,
            "type": run.type,
            "name": run.name,
            "description": run.description,
            "is_favorite": run.is_favorite,
            "progress_percent": run.progress_percent,
            "summary_json": run.summary_json,
            "completed_at": run.completed_at,
            "created_at": run.created_at,
        }

    async def edit_run(
        self, user_id: str, run_id: str, name: Optional[str] = None, description: Optional[str] = None
    ) -> tuple[int, ResearchRunResponseSchema]:
        """Update a run's name and/or description."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        # Verify strategy owner
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, run.strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        if name is not None:
            run.name = name
        if description is not None:
            run.description = description
        run.updated_at = datetime.utcnow()

        updated_run = await self.run_repository.update(run.id)
        return 200, ResearchRunResponseSchema.model_validate(updated_run)

    async def toggle_run_favorite(
        self, user_id: str, run_id: str, is_favorite: bool
    ) -> tuple[int, ResearchRunResponseSchema]:
        """Favorite or unfavorite a research run."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, run.strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run.is_favorite = is_favorite
        run.updated_at = datetime.utcnow()

        updated_run = await self.run_repository.update(run.id)
        return 200, ResearchRunResponseSchema.model_validate(updated_run)

    async def delete_run(self, user_id: str, run_id: str) -> tuple[int, dict]:
        """Permanently delete a run, its metadata, report, and dataset files."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, run.strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        # Delete from storage
        if run.metadata_s3_key:
            await storage_service.delete_payload(run.metadata_s3_key)
        if run.report_s3_key:
            await storage_service.delete_payload(run.report_s3_key)
        if run.dataset_s3_key:
            await storage_service.delete_payload(run.dataset_s3_key)

        await self.run_repository.delete(run_id)
        return 200, {"success": True, "message": "Research run deleted successfully."}

    async def get_run_progress(
        self, user_id: str, run_id: str
    ) -> tuple[int, ResearchRunProgressResponseSchema]:
        """Retrieve progress indicators for an active run."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, run.strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        progress = run.progress_json or {}
        return 200, ResearchRunProgressResponseSchema(
            status=run.status,
            progress_percent=run.progress_percent,
            processed_candles=progress.get("processed_candles"),
            total_candles=progress.get("total_candles"),
            completed_combinations=progress.get("completed_combinations"),
            total_combinations=progress.get("total_combinations"),
            completed_windows=progress.get("completed_windows"),
            total_windows=progress.get("total_windows"),
            completed_simulations=progress.get("completed_simulations"),
            total_simulations=progress.get("total_simulations"),
        )

    async def get_latest_run(
        self, user_id: str, strategy_id: str, run_type: str
    ) -> tuple[int, Dict[str, Any]]:
        """Download latest run directly from the latest/ storage folder."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        latest_key = f"reports/{strategy_id}/latest/{run_type.lower()}.msgpack.zstd"
        try:
            report_payload = await storage_service.download_payload(latest_key)
            return 200, report_payload
        except Exception:
            raise ResourceNotFoundException("Latest run not found for this strategy.")

    async def get_template_library(self, user_id: str) -> tuple[int, List[TemplateLibraryItemSchema]]:
        """List strategies that are marked as templates, returning their latest runs summaries."""
        strategies = await self.strategy_repository.get_by_user_id(user_id)
        templates = [s for s in strategies if s.is_template and not s.is_archived]

        items = []
        for temp in templates:
            latest = await self.run_repository.get_latest_results(temp.id)
            latest_backtest = None
            latest_optimization = None
            latest_walkforward = None
            latest_montecarlo = None

            if latest:
                if latest.latest_backtest_id:
                    bt = await self.run_repository.get_by_id(latest.latest_backtest_id)
                    latest_backtest = bt.summary_json if bt else None
                if latest.latest_optimization_id:
                    opt = await self.run_repository.get_by_id(latest.latest_optimization_id)
                    latest_optimization = opt.summary_json if opt else None
                if latest.latest_walkforward_id:
                    wf = await self.run_repository.get_by_id(latest.latest_walkforward_id)
                    latest_walkforward = wf.summary_json if wf else None
                if latest.latest_montecarlo_id:
                    mc = await self.run_repository.get_by_id(latest.latest_montecarlo_id)
                    latest_montecarlo = mc.summary_json if mc else None

            items.append(TemplateLibraryItemSchema(
                strategy_id=temp.id,
                strategy_name=temp.name,
                description=temp.description,
                latest_backtest=latest_backtest,
                latest_optimization=latest_optimization,
                latest_walkforward=latest_walkforward,
                latest_montecarlo=latest_montecarlo,
            ))

        return 200, items

    async def get_run_dataset_chart(
        self, user_id: str, run_id: str, dataset_name: str
    ) -> tuple[int, List[Any]]:
        """Download dataset zip file from storage and return specific chart curves."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, run.strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        if not run.dataset_s3_key:
            raise ResourceNotFoundException("Run dataset has no storage key.")

        try:
            dataset_payload = await storage_service.download_payload(run.dataset_s3_key)
        except Exception as e:
            logger.error(f"Failed to download dataset: {e}")
            raise ResourceNotFoundException("Dataset payload not found in storage.")

        chart_data = dataset_payload.get(dataset_name, [])
        return 200, chart_data
