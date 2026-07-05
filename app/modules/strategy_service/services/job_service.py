from datetime import datetime
from app.modules.strategy_service.schema.strategy_schema import JobStatus, RunType
from app.utils.time_utils import now_utc
from typing import Any, Dict, List, Optional
from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.research_run_model import ResearchRun
from app.modules.strategy_service.schema.strategy_schema import (
    ResearchRunResponseSchema,
    ResearchRunProgressResponseSchema,
    PaginatedResearchRunsResponseSchema,
    TemplateLibraryItemSchema,
)
from app.modules.strategy_service.services.storage_service import storage_service


class JobServiceMixin:
    async def trigger_backtest(
        self,
        user_id: str,
        strategy_id: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        parent_run_id: Optional[str] = None,
    ) -> tuple[int, dict]:
        """Submit a single backtest job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_asynchronous_backtest_task

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        active_version = await self._ensure_active_version(strategy)

        run = ResearchRun(
            strategy_id=strategy_id,
            run_type=RunType.BACKTEST,
            strategy_version_id=active_version.id,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=parent_run_id,
            name=f"Backtest {now_utc().strftime('%Y-%m-%d %H:%M')}",
            status=JobStatus.PENDING,
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
            strategy_version_id=active_version.id,
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": JobStatus.PENDING,
            "message": "Backtest enqueued successfully.",
        }

    async def trigger_optimization(
        self,
        user_id: str,
        strategy_id: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        parameter_space: list,
        constraints: list,
        objective: str,
        search_type: str,
        max_runs: int,
        parent_run_id: Optional[str] = None,
    ) -> tuple[int, dict]:
        """Submit an optimization job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_optimization_task

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        active_version = await self._ensure_active_version(strategy)

        run = ResearchRun(
            strategy_id=strategy_id,
            run_type=RunType.OPTIMIZATION,
            strategy_version_id=active_version.id,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=parent_run_id,
            name=f"Optimization {now_utc().strftime('%Y-%m-%d %H:%M')}",
            status=JobStatus.PENDING,
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
            strategy_version_id=active_version.id,
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": JobStatus.PENDING,
            "message": "Optimization enqueued successfully.",
        }

    async def trigger_walkforward(
        self,
        user_id: str,
        strategy_id: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        train_period_months: int,
        test_period_months: int,
        step_months: int,
        objective: str,
        parameter_space: list,
        constraints: list,
        window_type: str,
        parent_run_id: Optional[str] = None,
    ) -> tuple[int, dict]:
        """Submit a walkforward validation job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_walkforward_task

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
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
            run_type=RunType.WALKFORWARD,
            strategy_version_id=active_version.id,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=parent_run_id,
            name=f"WalkForward {now_utc().strftime('%Y-%m-%d %H:%M')}",
            status=JobStatus.PENDING,
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
            strategy_version_id=active_version.id,
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": JobStatus.PENDING,
            "message": "WalkForward enqueued successfully.",
        }

    async def trigger_montecarlo(
        self,
        user_id: str,
        strategy_id: str,
        source_backtest_id: str,
        simulation_count: int,
        method: str,
        random_seed: Optional[int],
    ) -> tuple[int, dict]:
        """Submit a Monte Carlo simulation job to the Celery worker."""
        from app.modules.strategy_service.tasks import run_montecarlo_task

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        active_version = await self._ensure_active_version(strategy)

        run = ResearchRun(
            strategy_id=strategy_id,
            run_type=RunType.MONTECARLO,
            strategy_version_id=active_version.id,
            compiled_hash=active_version.compiled_hash,
            parent_run_id=source_backtest_id,
            name=f"Monte Carlo {now_utc().strftime('%Y-%m-%d %H:%M')}",
            status=JobStatus.PENDING,
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
            strategy_version_id=active_version.id,
        )

        return 202, {
            "run_id": created_run.id,
            "task_id": task.id,
            "status": JobStatus.PENDING,
            "message": "Monte Carlo enqueued successfully.",
        }

    async def list_runs(
        self,
        user_id: str,
        strategy_id: str,
        run_type: Optional[str] = None,
        status: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        sort_by: str = "updated_at",
        page: int = 1,
        limit: int = 8,
    ) -> tuple[int, PaginatedResearchRunsResponseSchema]:
        """Get paginated history of research runs, sorted and filtered."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        paginated = await self.run_repository.get_runs_paginated(
            strategy_id=strategy_id,
            run_type=run_type,
            status=status,
            is_favorite=is_favorite,
            sort_by=sort_by,
            page=page,
            limit=limit,
        )

        return 200, PaginatedResearchRunsResponseSchema.model_validate(paginated)

    async def get_run(
        self, user_id: str, strategy_id: str, run_id: str
    ) -> tuple[int, Dict[str, Any]]:
        """Fetch details of a single run, returning the artifact manifest for lazy loading."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run = await self.run_repository.get_by_id(run_id)
        if not run or run.strategy_id != strategy_id:
            raise ResourceNotFoundException("Research run not found")

        return 200, {
            "id": run.id,
            "status": run.status,
            "type": run.run_type,
            "name": run.name,
            "description": run.description,
            "is_favorite": run.is_favorite,
            "progress_percent": run.progress_percent,
            "summary": run.summary_json,
            "artifacts": run.artifact_manifest,
            "completed_at": run.completed_at,
            "created_at": run.created_at,
            "run_hash": run.run_hash,
            "artifact_size_bytes": run.artifact_size_bytes,
            "strategy_version_id": run.strategy_version_id,
            "parent_run_id": run.parent_run_id,
            "updated_at": run.updated_at,
        }

    async def edit_run(
        self,
        user_id: str,
        run_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> tuple[int, ResearchRunResponseSchema]:
        """Update a run's name and/or description."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        # Verify strategy owner
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        if name is not None:
            run.name = name
        if description is not None:
            run.description = description
        run.updated_at = now_utc()

        updated_run = await self.run_repository.update(run.id)
        return 200, ResearchRunResponseSchema.model_validate(updated_run)

    async def toggle_run_favorite(
        self, user_id: str, run_id: str, is_favorite: bool
    ) -> tuple[int, ResearchRunResponseSchema]:
        """Favorite or unfavorite a research run."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        run.is_favorite = is_favorite
        run.updated_at = now_utc()

        updated_run = await self.run_repository.update(run.id)
        return 200, ResearchRunResponseSchema.model_validate(updated_run)

    async def delete_run(self, user_id: str, run_id: str) -> tuple[int, dict]:
        """Permanently delete a run, its metadata, report, and dataset files."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        # Delete from storage
        if run.artifact_manifest:
            for s3_key in run.artifact_manifest.values():
                if s3_key:
                    await storage_service.delete_payload(s3_key)

        await self.run_repository.delete(run_id)
        return 200, {"success": True, "message": "Research run deleted successfully."}

    async def get_run_progress(
        self, user_id: str, run_id: str
    ) -> tuple[int, ResearchRunProgressResponseSchema]:
        """Retrieve progress indicators for an active run."""
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ResourceNotFoundException("Research run not found")

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, run.strategy_id
        )
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
        """Retrieve latest run report by looking up latest run ID from database and downloading its S3 artifact."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")

        latest = await self.run_repository.get_latest_results(strategy_id)
        if not latest:
            raise ResourceNotFoundException("Latest run not found for this strategy.")

        latest_id_fields = {
            RunType.BACKTEST: "latest_backtest_id",
            RunType.OPTIMIZATION: "latest_optimization_id",
            RunType.WALKFORWARD: "latest_walkforward_id",
            RunType.MONTECARLO: "latest_montecarlo_id",
        }
        try:
            run_type_enum = RunType(run_type.upper())
        except ValueError:
            raise ResourceNotFoundException(f"Unknown run type '{run_type}'.")
        run_id = getattr(latest, latest_id_fields[run_type_enum])

        if not run_id:
            raise ResourceNotFoundException("Latest run not found for this strategy.")

        run = await self.run_repository.get_by_id(run_id)
        if not run or not run.report_s3_key:
            raise ResourceNotFoundException("Latest run report not found in storage.")

        try:
            report_payload = await storage_service.download_payload(run.report_s3_key)
            return 200, report_payload
        except Exception:
            raise ResourceNotFoundException("Latest run report not found in storage.")

    async def get_template_library(
        self, user_id: str
    ) -> tuple[int, List[TemplateLibraryItemSchema]]:
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
                    opt = await self.run_repository.get_by_id(
                        latest.latest_optimization_id
                    )
                    latest_optimization = opt.summary_json if opt else None
                if latest.latest_walkforward_id:
                    wf = await self.run_repository.get_by_id(
                        latest.latest_walkforward_id
                    )
                    latest_walkforward = wf.summary_json if wf else None
                if latest.latest_montecarlo_id:
                    mc = await self.run_repository.get_by_id(
                        latest.latest_montecarlo_id
                    )
                    latest_montecarlo = mc.summary_json if mc else None

            items.append(
                TemplateLibraryItemSchema(
                    strategy_id=temp.id,
                    strategy_name=temp.name,
                    description=temp.description,
                    latest_backtest=latest_backtest,
                    latest_optimization=latest_optimization,
                    latest_walkforward=latest_walkforward,
                    latest_montecarlo=latest_montecarlo,
                )
            )

        return 200, items
