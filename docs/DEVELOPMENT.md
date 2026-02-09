# Development Guide

## Setup

### First-Time Setup

```bash
# Clone the repository
git clone <repository-url>
cd api

# Run setup (installs dependencies + pre-commit hooks)
make setup

# Copy environment file for local development
cp .env.example .env.dev
```

### Environment Setup

Edit `.env.dev` with your configuration:

```env
# Application
ENV=development
DEBUG=True
APP_ENV=development

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db-dev:5432/crypalgos

# JWT Security
ACCESS_TOKEN_SECRET_KEY=dev-access-secret-change-in-production
REFRESH_TOKEN_SECRET_KEY=dev-refresh-secret-change-in-production
JWT_ALGORITHMS=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_MINUTES=10080

# Email Service (Resend)
RESEND_API_TOKEN=re_your_resend_api_key
RESEND_FROM_EMAIL=noreply@yourdomain.com
RESEND_FROM_NAME=CrypAlgos Team
```

Tip: If you need to force using a particular env file, set `ENV_FILE` before starting the application (example: `ENV_FILE=.env.dev make dev`). Otherwise the app chooses the env file using `APP_ENV`/`ENV` (default: `development`).

Note: If `APP_ENV` is only declared inside a `.env` file, the app won't be able to read it when choosing which env file to load. For local workflows prefer `ENV_FILE` or set `APP_ENV` externally (shell or `Makefile`) to be explicit.

## Daily Development

### Running the Application

````bash
# Start development server (hot-reload enabled)
make dev
You can also explicitly run the app with a different env file for testing or debugging, e.g.:

```bash
# Run the dev server but using production env values (NOT recommended for dev)
ENV_FILE=.env.prod APP_ENV=production make dev
````

# Or with uv directly

uv run fastapi dev app/main.py

# Or run using Docker Compose with development environment

```bash
docker-compose -f docker-compose-dev.yaml --env-file .env.dev up -d
```

````

Access the API:
- Main: http://localhost:8000
- Docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Code Quality

```bash
# Format code automatically
make format

# Run linting checks
make lint

# Type checking
make type-check

# Run all checks at once
make check
````

### Testing

```bash
# Run all tests (76 tests, 100% coverage)
make test

# With coverage report
make test-cov

# Run specific module tests
pytest tests/modules/user_service/routes/ -v  # Route tests
pytest tests/modules/user_service/services/ -v  # Service tests
pytest tests/modules/user_service/repositories/ -v  # Repository tests

# Run specific test
pytest tests/test_main.py::test_root_endpoint -v

# With verbose output
make test-verbose
```

### Test Structure

Our test suite has 100% coverage across all layers:

| Layer            | Tests    | Purpose                                         |
| ---------------- | -------- | ----------------------------------------------- |
| **Routes**       | 19 tests | API endpoint testing with mocked services       |
| **Services**     | 35 tests | Business logic testing with mocked repositories |
| **Repositories** | 22 tests | Data access testing with test database          |

**Key Testing Patterns:**

1. **Fixture-based Mocking**: Clean, reusable test fixtures in `conftest.py`
2. **Database Isolation**: Separate test database with Docker
3. **Dependency Override**: FastAPI's dependency injection for clean mocking
4. **Async Testing**: Full `pytest-asyncio` support

### Writing Tests

**Test Structure:**

```python
# tests/modules/user_service/services/test_user_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_get_user_by_id_success(
    user_service,           # Service instance from fixture
    mock_user_repository    # Mocked repository from fixture
):
    \"\"\"Test successful user retrieval.\"\"\"
    # Arrange
    user_id = \"test-user-id\"
    expected_user = MagicMock(id=user_id, email=\"test@test.com\")
    mock_user_repository.get_by_id = AsyncMock(return_value=expected_user)

    # Act
    result = await user_service.get_user_by_id(user_id)

    # Assert
    assert result == expected_user
    mock_user_repository.get_by_id.assert_called_once_with(user_id)
```

**Route Testing with Mocked Services:**

```python
# tests/modules/user_service/routes/test_user_routes.py
@pytest.mark.asyncio
async def test_get_current_user_profile(
    client,                      # TestClient from fixture
    override_user_service,       # Mocked service from fixture
    override_current_user        # Mocked auth from fixture
):
    \"\"\"Test GET /users/me endpoint.\"\"\"
    # Arrange
    user_data = {\"id\": \"user-1\", \"email\": \"test@test.com\"}
    override_user_service.get_user_by_id = AsyncMock(return_value=user_data)

    # Act
    response = client.get(\"/users/me\")

    # Assert
    assert response.status_code == 200
    assert response.json()[\"data\"][\"email\"] == \"test@test.com\"
```

## Adding Features

### 1. Adding a New Module

To add a new module (e.g., `strategy_service`):

## Adding Features

### 1. Adding a New Module

To add a new module (e.g., `strategy_service`):

```bash
# Create module structure
mkdir -p app/modules/strategy_service/{models,repositories,routes,services,schema,utils}

# Create __init__.py files
touch app/modules/strategy_service/{models,repositories,routes,services,schema,utils}/__init__.py
```

**Structure:**

```
app/modules/strategy_service/
├── models/
│   └── strategy_model.py       # SQLAlchemy model
├── repositories/
│   └── strategy_repository.py  # Data access layer
├── routes/
│   └── strategy_routes.py      # API endpoints
├── services/
│   └── strategy_service.py     # Business logic
├── schema/
│   └── strategy_schema.py      # Pydantic schemas
└── utils/
    └── strategy_utils.py       # Helper functions
```

### 2. Adding a New Endpoint

**Step 1: Define Schema**

```python
# app/modules/strategy_service/schema/strategy_schema.py
from pydantic import BaseModel

class StrategyCreateSchema(BaseModel):
    name: str
    description: str

class StrategyResponseSchema(BaseModel):
    id: str
    name: str
    description: str

    class Config:
        from_attributes = True
```

**Step 2: Create Model**

```python
# app/modules/strategy_service/models/strategy_model.py
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.config.base import Base

class Strategy(Base):
    __tablename__ = \"strategies\"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
```

**Step 3: Create Repository**

```python
# app/modules/strategy_service/repositories/strategy_repository.py
from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.strategy_model import Strategy

class StrategyRepository(BaseRepository[Strategy]):
    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(Strategy, db)
```

**Step 4: Create Service**

```python
# app/modules/strategy_service/services/strategy_service.py
import logging
from app.modules.strategy_service.repositories.strategy_repository import StrategyRepository

logger = logging.getLogger(__name__)

class StrategyService:
    def __init__(self, repository: StrategyRepository = Depends()):
        self.repository = repository

    async def create_strategy(self, data: dict):
        logger.info(f\"Creating strategy: {data['name']}\")
        strategy = Strategy(**data)
        return await self.repository.create(strategy)
```

**Step 5: Create Route**

```python
# app/modules/strategy_service/routes/strategy_routes.py
from fastapi import APIRouter, Depends
from app.modules.strategy_service.services.strategy_service import StrategyService
from app.advices.base_response_handler import BaseResponseHandler

router = APIRouter(prefix=\"/strategies\", tags=[\"strategies\"])

@router.post(\"/\")
async def create_strategy(
    data: StrategyCreateSchema,
    service: StrategyService = Depends()
):
    result = await service.create_strategy(data.model_dump())
    return BaseResponseHandler.success_response(result, status_code=201)
```

**Step 6: Register Router**

```python
# app/main.py
from app.modules.strategy_service.routes import strategy_routes

app.include_router(strategy_routes.router)
```

### 3. Create Database Migration

```bash
# Create migration
make create-migration msg=\"add strategies table\"

# Review generated migration file in alembic/versions/

# Apply migration
make migrate-dev
```

### 4. Write Tests

**Repository Test:**

```python
# tests/modules/strategy_service/repositories/test_strategy_repository.py
@pytest.mark.asyncio
async def test_create_strategy(strategy_repository, db_session):
    strategy = Strategy(name=\"Test Strategy\", description=\"Test\")
    result = await strategy_repository.create(strategy)

    assert result.id is not None
    assert result.name == \"Test Strategy\"
```

**Service Test:**

```python
# tests/modules/strategy_service/services/test_strategy_service.py
@pytest.mark.asyncio
async def test_create_strategy(strategy_service, mock_strategy_repository):
    data = {\"name\": \"Test\", \"description\": \"Test\"}
    mock_strategy_repository.create = AsyncMock(return_value=Strategy(**data))

    result = await strategy_service.create_strategy(data)

    assert result.name == \"Test\"
```

**Route Test:**

```python
# tests/modules/strategy_service/routes/test_strategy_routes.py
def test_create_strategy(client, override_strategy_service):
    response = client.post(\"/strategies/\", json={
        \"name\": \"Test\",
        \"description\": \"Test\"
    })

    assert response.status_code == 201
    assert response.json()[\"data\"][\"name\"] == \"Test\"
```

### 5. Code Quality Checklist

````bash
git checkout -b feature/your-feature-name

### 4. Run Quality Checks

```bash
# Must pass before committing
make check
````

### 5. Commit Changes

```bash
git add .
git commit -m \"feat: add user management endpoints\"
```

Pre-commit hooks will automatically:

- Format code with Ruff and Black
- Check for syntax errors
- Validate YAML/JSON files
- Check for large files
- Detect private keys

## Database Migrations

### Creating Migrations

```bash
# Create new migration
make migrate-create MESSAGE=\"add users table\"

# This generates: alembic/versions/xxx_add_users_table.py
```

### Applying Migrations

```bash
# Apply all pending migrations
make migrate-up

# Or manually
alembic upgrade head
```

### Rolling Back

```bash
# Rollback one migration
make migrate-down

# Or to specific version
alembic downgrade <revision>
```

### Migration Best Practices

1. **Always review generated migrations**

   ```python
   # Check the generated file before applying
   cat alembic/versions/xxx_add_users_table.py
   ```

2. **Test migrations both ways**
   ```bash
   make migrate-up    # Apply
   make migrate-down  # Rollback
   make migrate-up    # Apply again
   ```

### 5. Code Quality Checklist

Before committing:

```bash
# 1. Format code
make format

# 2. Run linters
make lint

# 3. Type checking
make type-check

# 4. Run tests
make test

# 5. Or run all checks at once
make check
```

### 6. Commit and Push

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m \"feat: add strategy management endpoints\"

# Push to remote
git push origin feature/strategy-management

# Create pull request on GitHub
```

## Database Migrations

### Creating Migrations

```bash
# Auto-generate migration from model changes
make create-migration msg=\"add strategies table\"

# Review the generated file in alembic/versions/
# Edit if needed

# Apply migration
make migrate-dev
```

### Migration Best Practices

1. **Review auto-generated migrations** - Always check before applying
2. **Test migrations** - Apply to dev database first
3. **Keep migrations atomic** - One logical change per migration
4. **Add rollback logic** - Ensure `downgrade()` works correctly

### Manual Migration Example

```python
# alembic/versions/xxx_add_strategies.py
def upgrade():
    op.create_table(
        'strategies',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_strategies_name', 'strategies', ['name'])

def downgrade():
    op.drop_index('ix_strategies_name', 'strategies')
    op.drop_table('strategies')
```

## Dependency Management

### Adding Dependencies

```bash
# Add production dependency
poetry add fastapi-users

# Add development dependency
poetry add --group dev pytest-asyncio

# Commit dependency files
git add pyproject.toml poetry.lock
git commit -m "Add new dependencies"
git add pyproject.toml poetry.lock requirements*.txt
git commit -m \"deps: add fastapi-users\"
```

### Why `make freeze`?

- Local development uses uv
- Production/Docker uses `requirements.txt`
- Always run `make freeze` after changing dependencies!

### Updating Dependencies

```bash
# Update specific package
uv add --upgrade fastapi

# Update all packages
uv lock --upgrade

# Export to requirements.txt
make freeze
```

## Code Style Guide

### Imports

```python
# Standard library
import os
from typing import Any

# Third-party
from fastapi import FastAPI, HTTPException
from sqlalchemy import select

# Local
from app.models import User
from app.services import UserService
```

### Naming Conventions

```python
# Variables and functions: snake_case
user_count = 10
def get_user_by_id(): pass

# Classes: PascalCase
class UserService: pass

# Constants: UPPER_SNAKE_CASE
MAX_CONNECTIONS = 100

# Private: _prefix
def _internal_helper(): pass
```

### FastAPI Patterns

```python
from fastapi import APIRouter, Depends
from typing import Annotated

router = APIRouter(prefix=\"/users\", tags=[\"users\"])

@router.get(\"/{user_id}\")
async def get_user(
    user_id: int,
    service: Annotated[UserService, Depends(get_user_service)]
) -> User:
    \"\"\"Get user by ID.\"\"\"
    return await service.get_user(user_id)
```

## Debugging

### Using Debugger

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or with Python 3.7+
breakpoint()
```

### Viewing Logs

```bash
# With Docker
make docker-logs

# Or follow logs
docker-compose -f docker-compose-dev.yaml logs -f api
```

### Database Debugging

```python
# Enable SQL logging in development
from sqlalchemy import create_engine

engine = create_engine(
    DATABASE_URL,
    echo=True  # Logs all SQL queries
)
```

## Common Issues

### Pre-commit Hooks Failing

```bash
# Run manually to see issues
pre-commit run --all-files

# Fix formatting issues automatically
make format

# Re-run checks
make check
```

### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>
```

### Database Connection Issues

```bash
# Check if PostgreSQL is running
docker ps | grep postgres

# Restart database
make docker-down
make docker-up
```

### Import Errors

```bash
# Ensure you're in the virtual environment
poetry shell

# Or use poetry run
poetry run python -c \"import app\"
```

## Best Practices

### 1. Write Tests First (TDD)

```python
# Write the test
def test_create_user():
    assert create_user(\"john\") is not None

# Then implement the feature
def create_user(name: str) -> User:
    return User(name=name)
```

### 2. Keep Functions Small

- One function = one responsibility
- Max 20-30 lines per function
- Extract complex logic into helpers

### 3. Use Type Hints Everywhere

```python
# Good
def process(data: dict[str, Any]) -> Result:
    pass

# Bad
def process(data):
    pass
```

### 4. Handle Errors Gracefully

```python
try:
    result = await process_data(data)
except ValidationError as e:
    raise HTTPException(400, detail=str(e))
except DatabaseError:
    raise HTTPException(500, detail=\"Database error\")
```

### 5. Document Public APIs

- All public functions need docstrings
- Include examples in docstrings
- Keep documentation up to date

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org)
- [Pytest Documentation](https://docs.pytest.org)
- [Type Hints (PEP 484)](https://peps.python.org/pep-0484/)
