import logging
from datetime import datetime

from app.exceptions.exceptions import ResourceNotFoundException
from crypalgos_core.compiler import compile_dag, DAGCompiler
from app.modules.strategy_service.models.strategy_model import Strategy
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository
from app.modules.strategy_service.schema.strategy_schema import (
    StrategyResponseSchema,
    PaginatedStrategiesResponseSchema,
)

# To support mock patching of DAGCompiler.compile_dag in service tests
if not hasattr(DAGCompiler, "compile_dag"):
    DAGCompiler.compile_dag = staticmethod(compile_dag)

logger = logging.getLogger(__name__)

# Strategy service managing visual canvases and python code generation

class StrategyService:
    def __init__(
        self,
        strategy_repository: StrategyRepository,
    ):
        self.strategy_repository = strategy_repository

    async def create_strategy(
        self, user_id: str, name: str, description: str | None, canvas_json: dict
    ) -> tuple[int, StrategyResponseSchema]:
        """Convert a user's visual pipeline configuration into executable python code."""
        compiler = DAGCompiler()
        compiled_script = compiler.compile_dag(canvas_json)
        
        strategy = Strategy(
            user_id=user_id,
            name=name,
            description=description,
            canvas_json=canvas_json,
            compiled_code=compiled_script
        )
        created_strategy = await self.strategy_repository.create(strategy)
        return 201, StrategyResponseSchema.model_validate(created_strategy)

    async def save_strategy_code(
        self, user_id: str, strategy_id: str, compiled_code: str
    ) -> tuple[int, StrategyResponseSchema]:
        """Directly overwrite strategy python script."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
            
        strategy.compiled_code = compiled_code
        strategy.updated_at = datetime.utcnow()
        
        updated_strategy = await self.strategy_repository.update(strategy)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)
        
    async def get_strategy(self, user_id: str, strategy_id: str) -> tuple[int, StrategyResponseSchema]:
        """Retrieve a specific visual strategy layout."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
        return 200, StrategyResponseSchema.model_validate(strategy)

    async def list_strategies(
        self, user_id: str, page: int = 1, limit: int = 8
    ) -> tuple[int, PaginatedStrategiesResponseSchema]:
        """Retrieve paginated summary list of user strategies."""
        paginated_data = await self.strategy_repository.get_paginated_strategies(user_id, page, limit)
        return 200, PaginatedStrategiesResponseSchema.model_validate(paginated_data)

    async def delete_strategy(self, user_id: str, strategy_id: str) -> tuple[int, dict]:
        """Delete a given visual strategy entirely including all its compiled artifacts."""
        strategy = await self.strategy_repository.get_by_user_and_id(user_id, strategy_id)
        if not strategy:
            raise ResourceNotFoundException("Strategy not found")
            
        await self.strategy_repository.delete(strategy_id)
        return 200, {"success": True, "message": "Strategy deleted successfully."}
