# Architecture Overview

## System Design

### High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Client Layer                      │
│          (Web, Mobile, CLI, External APIs)           │
└─────────────────────────────┬───────────────────────┘
                              │
                    HTTPS/REST API
                              │
┌─────────────────────────────▼───────────────────────┐
│                   FastAPI Application                 │
│                                                       │
│  ┌──────────────────────────────────────────────┐   │
│  │         Auth Middleware (JWT)                │   │
│  │  (Validates tokens, extracts user context)   │   │
│  └──────────────────────────────────────────────┘   │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │   Routes     │──│   Services   │──│  Repos   │  │
│  │ (API Layer)  │  │  (Business)  │  │  (Data)  │  │
│  └──────────────┘  └──────────────┘  └──────────┘  │
│                                                       │
└─────────────────────────────┬───────────────────────┘
                              │
          ┌───────────────────┼────────────────────┐
          │                   │                    │
┌─────────▼─────┐   ┌─────────▼────────┐   ┌──────▼──────┐
│  PostgreSQL   │   │  Email Service   │   │   Logging   │
│   (Async)     │   │    (Resend)      │   │  (Stdout)   │
└───────────────┘   └──────────────────┘   └─────────────┘
```

## Project Structure

### Directory Layout

```
api/
├── app/                              # Application code
│   ├── main.py                       # FastAPI application
│   │
│   ├── config/                       # Configuration
│   │   ├── base.py                   # Base config classes
│   │   ├── base_repositories.py      # Generic repository
│   │   └── settings.py               # App settings (Pydantic)
│   │
│   ├── db/                           # Database
│   │   └── connect_db.py             # AsyncSession factory
│   │
│   ├── advices/                      # Response handlers
│   │   ├── base_response_handler.py  # Success/error responses
│   │   ├── global_exception_handler.py
│   │   └── responses.py              # Response models
│   │
│   ├── exceptions/                   # Custom exceptions
│   │   └── exceptions.py
│   │
│   ├── middlewares/                  # Middleware
│   │   └── auth_middleware.py        # JWT validation
│   │
│   ├── mail/                         # Email service
│   │   ├── service/
│   │   │   └── resend_service.py     # Resend API integration
│   │   ├── templates/                # Email templates
│   │   └── template_renderer.py
│   │
│   └── modules/                      # Feature modules
│       └── user_service/             # User management
│           ├── models/               # SQLAlchemy ORM
│           │   ├── user_model.py
│           │   ├── session_model.py
│           │   └── subscription_model.py
│           ├── repositories/         # Data access
│           │   ├── user_repository.py
│           │   ├── session_repository.py
│           │   └── subscription_repository.py
│           ├── routes/               # API endpoints
│           │   ├── auth_routes.py
│           │   ├── user_routes.py
│           │   └── session_routes.py
│           ├── schema/               # Pydantic schemas
│           │   ├── user_schema.py
│           │   └── session_schema.py
│           ├── services/             # Business logic
│           │   ├── auth_service.py
│           │   ├── user_service.py
│           │   ├── session_service.py
│           │   └── subscription_service.py
│           └── utils/                # Utilities
│               └── auth_utils.py     # JWT & password hashing
│
├── tests/                            # Test suite (76 tests)
│   ├── conftest.py                   # Root fixtures
│   ├── test_main.py
│   └── modules/
│       └── user_service/
│           ├── conftest.py           # Module fixtures
│           ├── repositories/         # 22 tests
│           ├── services/             # 35 tests
│           └── routes/               # 19 tests
│
└── alembic/                          # Database migrations
    ├── env.py
    └── versions/
    └── versions/
```

## Design Patterns

### 1. Layered Architecture

**Router Layer** (API Routes)
```python
# app/routers/users.py
from fastapi import APIRouter, Depends
from app.controllers import UserController

router = APIRouter(prefix=\"/users\", tags=[\"users\"])

@router.get(\"/{user_id}\")
async def get_user(
    user_id: int,
    controller: UserController = Depends()
):
    return await controller.get_user(user_id)
```

**Controller Layer** (Request/Response Handling)
```python
# app/controllers/user_controller.py
from fastapi import HTTPException
from app.services import UserService
from app.schemas import UserResponse

class UserController:
    def __init__(self, service: UserService = Depends()):
        self.service = service

    async def get_user(self, user_id: int) -> UserResponse:
        user = await self.service.get_user(user_id)
        if not user:
            raise HTTPException(404, \"User not found\")
        return UserResponse.from_orm(user)
```

**Service Layer** (Business Logic)
```python
# app/services/user_service.py
from app.models import User
from app.database import AsyncSession

class UserService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def get_user(self, user_id: int) -> User | None:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
```

### 2. Dependency Injection

```python
# app/dependencies.py
from typing import Annotated
from fastapi import Depends

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    # Validate token and return user
    return user

# Usage
@router.get(\"/me\")
async def get_profile(
    user: Annotated[User, Depends(get_current_user)]
):
    return user
```

### 3. Repository Pattern (Generic Base)

We use a generic base repository for common CRUD operations:

```python
# app/config/base_repositories.py
from typing import Generic, TypeVar, Type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

T = TypeVar("T")

class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T], db: AsyncSession):
        self.model = model
        self.db = db

    async def create(self, entity: T) -> T:
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_by_id(self, id: str) -> T | None:
        return await self.db.get(self.model, id)

    async def get_all(self) -> list[T]:
        result = await self.db.execute(select(self.model))
        return list(result.scalars().all())

    async def delete(self, entity: T) -> None:
        await self.db.delete(entity)

# Usage in specific repositories
class UserRepository(BaseRepository[User]):
    def __init__(self, db: AsyncSession = Depends(get_db)):
        super().__init__(User, db)

    # Add custom queries
    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user
```

### 4. Response Handlers

```python
# app/advices/base_response_handler.py
from fastapi.responses import JSONResponse
from app.advices.responses import ApiResponse, ApiError

class BaseResponseHandler:
    @staticmethod
    def success_response(data: Any = None, status_code: int = 200):
        return JSONResponse(
            status_code=status_code,
            content=ApiResponse(data=data).model_dump(mode=\"json\")
        )

    @staticmethod
    def error_response(message: str, status_code: int, errors: dict | None = None):
        api_error = ApiError(status_code=status_code, message=message, errors=errors)
        return JSONResponse(
            status_code=status_code,
            content=ApiResponse(api_error=api_error).model_dump(mode=\"json\")
        )
```

### 5. Schema Validation (Pydantic)

```python
# app/modules/user_service/schema/user_schema.py
from pydantic import BaseModel, EmailStr, field_validator

class UserRegisterSchema(BaseModel):
    email: EmailStr
    username: str
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

class UserResponseSchema(BaseModel):
    id: str
    email: EmailStr
    username: str
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True  # Allows ORM model conversion
```

## Authentication & Session Management

### Authentication Flow

```
1. Registration Flow
   POST /auth/register
   ├─> Validate input (Pydantic)
   ├─> Hash password (bcrypt)
   ├─> Create user (unverified)
   ├─> Generate 6-digit code
   ├─> Send verification email
   └─> Return success

2. Verification Flow
   POST /auth/verify
   ├─> Validate code & expiry
   ├─> Mark user verified
   ├─> Create session
   ├─> Generate JWT tokens
   └─> Return tokens + user

3. Login Flow
   POST /auth/login
   ├─> Verify credentials
   ├─> Check is_verified
   ├─> Create/update session
   ├─> Generate JWT tokens
   └─> Return tokens + user
```

### JWT Token Structure

```python
# Access Token (30 min)
{
    \"user_id\": \"uuid\",
    \"email\": \"user@example.com\",
    \"exp\": 1234567890,
    \"iat\": 1234567860
}

# Refresh Token (7 days)
{
    \"user_id\": \"uuid\",
    \"session_id\": \"uuid\",
    \"exp\": 1235172660,
    \"iat\": 1234567860
}
```

### Auth Middleware

```python
# app/middlewares/auth_middleware.py
async def get_current_user(request: Request) -> dict:
    # Skip in test environment
    if os.getenv(\"APP_ENV\") == \"testing\":
        return {\"user_id\": \"test-user\", \"email\": \"test@test.com\"}

    # Extract and verify token
    auth_header = request.headers.get(\"Authorization\")
    if not auth_header:
        raise HTTPException(401, \"Missing token\")

    token = auth_header.split(\" \")[1]
    payload = verify_token(token, \"access\")

    return {\"user_id\": payload[\"user_id\"], \"email\": payload[\"email\"]}
```

## Database Design

### Entity Relationship Diagram

```
┌────────────────────────┐
│        User            │
├────────────────────────┤
│ id (PK)                │
│ email (unique)         │
│ username (unique)      │
│ password (hashed)      │
│ is_verified            │
│ verification_code      │
│ code_expires_at        │
│ created_at             │
│ updated_at             │
└────────────┬───────────┘
             │ 1
             │
             │ N
┌────────────▼───────────┐
│      Session           │
├────────────────────────┤
│ id (PK)                │
│ user_id (FK)           │
│ refresh_token          │
│ device_info            │
│ ip_address             │
│ is_active              │
│ last_accessed_at       │
│ expires_at             │
│ created_at             │
└────────────────────────┘
```

### Database Connection

```python
# app/db/connect_db.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)

async_session_maker = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    async with async_session_maker() as session:
        async with session.begin():
            yield session
```

### Model Definition

```python
# app/modules/user_service/models/user_model.py
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.config.base import Base

class User(Base):
    __tablename__ = \"users\"

    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_code: Mapped[str | None] = mapped_column(String, nullable=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

## API Design

### RESTful Conventions

```python
# Authentication Endpoints
POST   /auth/register           # Register new user
POST   /auth/verify             # Verify email
POST   /auth/login              # Login user
POST   /auth/logout             # Logout current session
POST   /auth/logout/all         # Logout all sessions
POST   /auth/refresh            # Refresh access token
POST   /auth/forgot-password    # Request password reset
POST   /auth/reset-password     # Reset password

# User Endpoints
GET    /users/me                # Get current user profile
PUT    /users/me                # Update current user
DELETE /users/me                # Delete current user

# Session Endpoints
GET    /sessions                # List user sessions
GET    /sessions/{id}           # Get specific session
DELETE /sessions/{id}           # Delete specific session
DELETE /sessions                # Delete all sessions
DELETE /users/{id}     # Delete user

# Nested resources: /users/{id}/posts
GET    /users/{id}/posts     # Get user's posts
POST   /users/{id}/posts     # Create post for user
```

### Response Format

```python
# Success response
{
    \"id\": 1,
    \"email\": \"user@example.com\",
    \"name\": \"John Doe\"
}

# Error response
{
    \"detail\": \"User not found\"
}

# Validation error
{
    \"detail\": [
        {
            \"loc\": [\"body\", \"email\"],
            \"msg\": \"Invalid email format\",
            \"type\": \"value_error\"
        }
    ]
}
```

## Security

### Authentication Flow

```python
# app/security/auth.py
from passlib.context import CryptContext
from jose import jwt

pwd_context = CryptContext(schemes=[\"bcrypt\"], deprecated=\"auto\")

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE)
    to_encode.update({\"exp\": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
```

### Authorization

```python
# app/middleware/auth.py
from fastapi import Security
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def require_admin(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> User:
    token = credentials.credentials
    user = decode_token(token)
    if not user.is_admin:
        raise HTTPException(403, \"Admin access required\")
    return user
```

## Error Handling

### Global Exception Handler

```python
# app/main.py
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={\"detail\": str(exc)}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f\"Unhandled exception: {exc}\", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={\"detail\": \"Internal server error\"}
    )
```

## Performance

### Caching Strategy

```python
# app/cache.py
from functools import lru_cache
from redis import asyncio as aioredis

redis_client = aioredis.from_url(\"redis://localhost\")

async def get_cached(key: str) -> str | None:
    return await redis_client.get(key)

async def set_cached(key: str, value: str, expire: int = 3600):
    await redis_client.setex(key, expire, value)

# Usage
@router.get(\"/users/{user_id}\")
async def get_user(user_id: int):
    cached = await get_cached(f\"user:{user_id}\")
    if cached:
        return json.loads(cached)

    user = await service.get_user(user_id)
    await set_cached(f\"user:{user_id}\", user.json())
    return user
```

### Query Optimization

```python
# Use eager loading to avoid N+1 queries
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(User)
    .options(selectinload(User.posts))
    .where(User.id == user_id)
)
```

## Testing Strategy

### Test Pyramid

```
         ┌──────────┐
         │   E2E    │  <- Few (10%)
         ├──────────┤
         │Integration│  <- Some (30%)
         ├──────────┤
         │   Unit    │  <- Many (60%)
         └──────────┘
```

### Test Structure

```python
# tests/unit/test_user_service.py
@pytest.mark.asyncio
async def test_get_user_success(mock_db):
    service = UserService(mock_db)
    user = await service.get_user(1)
    assert user.id == 1

# tests/integration/test_user_api.py
async def test_create_user_endpoint(client, db):
    response = client.post(\"/users\", json={
        \"email\": \"test@example.com\",
        \"password\": \"password123\",
        \"name\": \"Test User\"
    })
    assert response.status_code == 201
```

## Deployment Architecture

### Production Setup

```
Internet
    │
    ▼
┌─────────────┐
│  Nginx/     │  <- SSL termination, load balancing
│  Traefik    │
└──────┬──────┘
       │
       ▼
┌──────────────────────────────┐
│   Docker Containers (3x)      │
│   ┌────┐  ┌────┐  ┌────┐    │
│   │API │  │API │  │API │    │
│   └────┘  └────┘  └────┘    │
└──────────────────────────────┘
       │
       ▼
┌──────────────┐  ┌──────────┐
│  PostgreSQL  │  │  Redis   │
│  (Primary)   │  │ (Cache)  │
└──────────────┘  └──────────┘
```

## Monitoring

### Health Checks

```python
@app.get(\"/health\")
async def health_check():
    return {
        \"status\": \"healthy\",
        \"version\": __version__,
        \"timestamp\": datetime.utcnow().isoformat()
    }

@app.get(\"/health/db\")
async def db_health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(select(1))
        return {\"status\": \"healthy\"}
    except Exception as e:
        return {\"status\": \"unhealthy\", \"error\": str(e)}
```

### Logging

```python
# app/logging_config.py
import logging
from pythonjsonlogger import jsonlogger

handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)
```

## Best Practices

1. **Keep layers separated** - Don't mix business logic with HTTP handling
2. **Use dependency injection** - Makes testing easier
3. **Validate at the edge** - Use Pydantic schemas for all inputs
4. **Handle errors gracefully** - Return proper HTTP status codes
5. **Document your API** - FastAPI generates OpenAPI docs automatically
6. **Write tests** - Aim for >80% coverage
7. **Use async/await** - For I/O-bound operations
8. **Cache strategically** - Reduce database load
9. **Monitor everything** - Logs, metrics, traces
10. **Keep it simple** - Don't over-engineer
