import logging
import hashlib
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
    SaveVersionRequestSchema,
    StrategyVersionResponseSchema,
    VersionDiffResponseSchema,
    ResearchNoteResponseSchema,
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
            strategy_type="VISUAL",
            source_code=None,
            compiled_hash=hashlib.sha256(compiled_script.encode("utf-8")).hexdigest() if isinstance(compiled_script, str) else "mock_hash",
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
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
            
        strategy.compiled_code = code
        strategy.source_code = code
        strategy.is_code_modified = True
        strategy.strategy_type = "CODE"
        strategy.has_unpublished_changes = True
        strategy.compiled_hash = hashlib.sha256(code.encode("utf-8")).hexdigest() if isinstance(code, str) else "mock_hash"
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
        strategy.strategy_type = "VISUAL"
        strategy.has_unpublished_changes = True
        strategy.compiled_hash = hashlib.sha256(compiled_script.encode("utf-8")).hexdigest() if isinstance(compiled_script, str) else "mock_hash"
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
        strategy.strategy_type = "VISUAL"
        strategy.has_unpublished_changes = True
        strategy.compiled_hash = hashlib.sha256(compiled_script.encode("utf-8")).hexdigest() if isinstance(compiled_script, str) else "mock_hash"
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
        self, user_id: str, strategy_id: str, start_date: datetime, end_date: datetime, initial_capital: float,
        parent_run_id: Optional[str] = None
    ) -> tuple[int, dict]:
        """Submit a single backtest job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_asynchronous_backtest_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        active_version = await self._ensure_active_version(strategy)

        run = ResearchRun(
            strategy_id=strategy_id,
            type="BACKTEST",
            strategy_version_id=active_version.id,
            strategy_version=active_version.version,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=parent_run_id,
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
            initial_capital=initial_capital,
            strategy_version_id=active_version.id
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": "PENDING",
            "message": "Backtest enqueued successfully."
        }

    async def trigger_optimization(
        self, user_id: str, strategy_id: str, start_date: datetime, end_date: datetime, initial_capital: float,
        parameter_space: list, constraints: list, objective: str, search_type: str, max_runs: int,
        parent_run_id: Optional[str] = None
    ) -> tuple[int, dict]:
        """Submit an optimization job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_optimization_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        active_version = await self._ensure_active_version(strategy)

        run = ResearchRun(
            strategy_id=strategy_id,
            type="OPTIMIZATION",
            strategy_version_id=active_version.id,
            strategy_version=active_version.version,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=parent_run_id,
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
            strategy_version_id=active_version.id
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
        parameter_space: list, constraints: list, window_type: str, parent_run_id: Optional[str] = None
    ) -> tuple[int, dict]:
        """Submit a walkforward validation job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_walkforward_task

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        active_version = await self._ensure_active_version(strategy)

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
            strategy_version_id=active_version.id,
            strategy_version=active_version.version,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=parent_run_id,
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
            strategy_version_id=active_version.id
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

        active_version = await self._ensure_active_version(strategy)

        run = ResearchRun(
            strategy_id=strategy_id,
            type="MONTECARLO",
            strategy_version_id=active_version.id,
            strategy_version=active_version.version,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=source_backtest_id,
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
            strategy_version_id=active_version.id
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

    async def _ensure_active_version(self, strategy: Strategy) -> Any:
        """
        Ensures a strategy has an active/immutable version snapshot.
        If has_unpublished_changes is True (or current_version is 0),
        creates a new StrategyVersion snapshot, increments current_version, and marks has_unpublished_changes = False.
        Otherwise, returns the StrategyVersion corresponding to current_version.
        """
        from sqlalchemy import select, func
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        # Calculate compiled hash of current draft code
        if isinstance(strategy.compiled_code, str):
            code_bytes = strategy.compiled_code.encode("utf-8")
            current_hash = hashlib.sha256(code_bytes).hexdigest()
        else:
            current_hash = "mock_hash"
        strategy.compiled_hash = current_hash


        if not strategy.has_unpublished_changes and strategy.current_version > 0:
            # Look up existing version
            stmt = select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy.id,
                StrategyVersion.version == strategy.current_version
            )
            res = await self.strategy_repository.session.execute(stmt)
            existing_version = res.scalar_one_or_none()
            if existing_version:
                return existing_version

        # Otherwise, create a new version snapshot
        # Find maximum version number for this strategy
        max_ver_stmt = select(func.max(StrategyVersion.version)).where(
            StrategyVersion.strategy_id == strategy.id
        )
        max_ver_res = await self.strategy_repository.session.execute(max_ver_stmt)
        max_ver = max_ver_res.scalar() or 0
        new_version = max_ver + 1

        new_snapshot = StrategyVersion(
            strategy_id=strategy.id,
            version=new_version,
            commit_message=f"Auto-snapshot before run version {new_version}",
            canvas_json=strategy.canvas_json,
            source_code=strategy.source_code,
            compiled_code=strategy.compiled_code,
            compiled_hash=current_hash,
            is_code_modified=strategy.is_code_modified,
        )
        self.strategy_repository.session.add(new_snapshot)
        await self.strategy_repository.session.flush()

        strategy.current_version = new_version
        strategy.has_unpublished_changes = False
        strategy.updated_at = datetime.utcnow()  # type: ignore[assignment]
        await self.strategy_repository.update(strategy.id)

        return new_snapshot

    async def save_version(
        self, user_id: str, strategy_id: str, commit_message: str | None
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Manually save a snapshot version of the strategy draft."""
        from sqlalchemy import select, func
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        # Calculate compiled hash of current draft code
        if isinstance(strategy.compiled_code, str):
            code_bytes = strategy.compiled_code.encode("utf-8")
            current_hash = hashlib.sha256(code_bytes).hexdigest()
        else:
            current_hash = "mock_hash"
        strategy.compiled_hash = current_hash


        # Get max version
        max_ver_stmt = select(func.max(StrategyVersion.version)).where(
            StrategyVersion.strategy_id == strategy.id
        )
        max_ver_res = await self.strategy_repository.session.execute(max_ver_stmt)
        max_ver = max_ver_res.scalar() or 0
        new_version = max_ver + 1

        new_snapshot = StrategyVersion(
            strategy_id=strategy.id,
            version=new_version,
            commit_message=commit_message or f"Manual snapshot version {new_version}",
            canvas_json=strategy.canvas_json,
            source_code=strategy.source_code,
            compiled_code=strategy.compiled_code,
            compiled_hash=current_hash,
            is_code_modified=strategy.is_code_modified,
        )
        self.strategy_repository.session.add(new_snapshot)
        await self.strategy_repository.session.flush()

        strategy.current_version = new_version
        strategy.has_unpublished_changes = False
        strategy.updated_at = datetime.utcnow()  # type: ignore[assignment]
        await self.strategy_repository.update(strategy.id)

        return 201, StrategyVersionResponseSchema.model_validate(new_snapshot)

    async def list_versions(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, list[StrategyVersionResponseSchema]]:
        """List version history of a strategy."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id
        ).order_by(StrategyVersion.version.desc())
        res = await self.strategy_repository.session.execute(stmt)
        versions = res.scalars().all()
        return 200, [StrategyVersionResponseSchema.model_validate(v) for v in versions]

    async def get_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Fetch details of a specific strategy version."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")
        return 200, StrategyVersionResponseSchema.model_validate(snapshot)

    async def restore_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, StrategyResponseSchema]:
        """Restore a historical version snapshot into the current draft, setting has_unpublished_changes = True."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        # Copy snapshot fields into the strategy draft
        strategy.canvas_json = snapshot.canvas_json or {}
        strategy.source_code = snapshot.source_code
        strategy.compiled_code = snapshot.compiled_code
        strategy.compiled_hash = snapshot.compiled_hash
        strategy.is_code_modified = snapshot.is_code_modified
        strategy.strategy_type = "CODE" if snapshot.is_code_modified else "VISUAL"
        
        # In restore workflow: retaining the active version index but setting has_unpublished_changes = True
        strategy.current_version = snapshot.version
        strategy.has_unpublished_changes = True
        strategy.updated_at = datetime.utcnow()  # type: ignore[assignment]
        
        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)

    async def diff_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, VersionDiffResponseSchema]:
        """Compare a version snapshot against the current draft."""
        import difflib
        from sqlalchemy import select
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        # Compute unified diff of compiled_code
        version_code_lines = snapshot.compiled_code.splitlines(keepends=True)
        draft_code_lines = strategy.compiled_code.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            version_code_lines,
            draft_code_lines,
            fromfile=f"version_{version}",
            tofile="draft",
        )
        diff_str = "".join(diff)

        # Check if canvas changed
        canvas_changed = snapshot.canvas_json != strategy.canvas_json

        return 200, VersionDiffResponseSchema(
            diff_code=diff_str,
            canvas_changed=canvas_changed
        )

    async def update_version_label(
        self, user_id: str, strategy_id: str, version: int, label: str | None
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Update label of a specific strategy version snapshot."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        snapshot.label = label
        await self.strategy_repository.session.commit()
        return 200, StrategyVersionResponseSchema.model_validate(snapshot)

    async def update_version_approval(
        self, user_id: str, strategy_id: str, version: int, status: str
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Update approval status of a specific strategy version snapshot."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        ALLOWED_STATUSES = {"DRAFT", "REVIEWING", "APPROVED", "REJECTED", "PAPER_TRADING", "LIVE"}
        status_upper = status.upper()
        if status_upper not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid approval status. Must be one of: {ALLOWED_STATUSES}")

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        snapshot.approval_status = status_upper
        await self.strategy_repository.session.commit()
        return 200, StrategyVersionResponseSchema.model_validate(snapshot)

    async def set_golden_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, StrategyResponseSchema]:
        """Set a historical version snapshot as the golden candidate for the strategy."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.strategy_version_model import StrategyVersion

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        strategy.golden_version_id = snapshot.id
        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)

    async def create_research_note(
        self, user_id: str, strategy_id: str, content: str, run_id: str | None = None
    ) -> tuple[int, ResearchNoteResponseSchema]:
        """Create a new research note for a strategy (optionally linked to a run)."""
        from app.modules.strategy_service.models.research_note_model import ResearchNote

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        if run_id:
            run = await self.run_repository.get_by_id(run_id)
            if not run or run.strategy_id != strategy_id:
                raise ResourceNotFoundException("Research run not found or does not belong to this strategy")

        new_note = ResearchNote(
            strategy_id=strategy_id,
            run_id=run_id,
            content=content
        )
        self.strategy_repository.session.add(new_note)
        await self.strategy_repository.session.commit()
        return 201, ResearchNoteResponseSchema.model_validate(new_note)

    async def list_strategy_notes(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, list[ResearchNoteResponseSchema]]:
        """List all research notes for a strategy."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.research_note_model import ResearchNote

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(ResearchNote).where(
            ResearchNote.strategy_id == strategy_id
        ).order_by(ResearchNote.created_at.desc())
        res = await self.strategy_repository.session.execute(stmt)
        notes = res.scalars().all()
        return 200, [ResearchNoteResponseSchema.model_validate(n) for n in notes]

    async def list_run_notes(
        self, user_id: str, strategy_id: str, run_id: str
    ) -> tuple[int, list[ResearchNoteResponseSchema]]:
        """List all research notes for a specific run."""
        from sqlalchemy import select
        from app.modules.strategy_service.models.research_note_model import ResearchNote

        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        run = await self.run_repository.get_by_id(run_id)
        if not run or run.strategy_id != strategy_id:
            raise ResourceNotFoundException("Research run not found")

        stmt = select(ResearchNote).where(
            ResearchNote.strategy_id == strategy_id,
            ResearchNote.run_id == run_id
        ).order_by(ResearchNote.created_at.desc())
        res = await self.strategy_repository.session.execute(stmt)
        notes = res.scalars().all()
        return 200, [ResearchNoteResponseSchema.model_validate(n) for n in notes]


