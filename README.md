# CrypAlgos API

> A production-ready FastAPI application for cryptocurrency trading algorithms with comprehensive user management and authentication.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.121+-green.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-76%20passed-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](tests/)

## ✨ Features

### Core Infrastructure

- 🚀 **FastAPI** - Modern, fast async web framework
- 🐘 **PostgreSQL** - Robust database with async SQLAlchemy
- 🔄 **Alembic** - Database migration management
- 🐳 **Docker** - Production-ready containerization
- 📧 **Email Service** - Resend integration for transactional emails

### Authentication & Security

- 🔐 **JWT Authentication** - Secure token-based auth with refresh tokens
- 🔑 **Session Management** - Multi-device session tracking
- 👤 **User Management** - Complete CRUD operations with verification
- 🛡️ **Security Middleware** - Request validation and rate limiting
- 📧 **Email Verification** - Two-factor verification flow

### Code Quality

- ✅ **100% Test Coverage** - 76 comprehensive tests
- 🧪 **Pytest** - Async test suite with fixtures
- 📝 **Type Safety** - Full type hints with MyPy
- 📊 **Professional Logging** - Structured logging across all layers
- 🎨 **Code Quality** - Ruff, Black, pre-commit hooks

## 📋 Prerequisites

- **Python 3.12+**
- **uv** (local development only)
- **Docker & Docker Compose** (for containerized deployment)

## 🚀 Quick Start

### Local Development

```bash
# One-time setup
make setup

# Start development server (with hot-reload)
make dev

# Or with Docker (includes PostgreSQL)
make docker-up
```

The API will be available at:

- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

### Running Tests

```bash
# Run all tests (76 tests)
make test

# Run with coverage report
make test-cov

# Run specific test module
pytest tests/modules/user_service/routes/test_auth_routes.py -v
```

### Production Deployment

```bash
# Deploy with Docker Compose
make docker-prod-up
```

## 🔐 API Endpoints

### Authentication (`/api/v1/auth`)

| Method | Endpoint                   | Description                | Auth Required |
| ------ | -------------------------- | -------------------------- | ------------- |
| POST   | `/register`                | Register new user          | ❌            |
| POST   | `/login`                   | Login user                 | ❌            |
| POST   | `/verify`                  | Verify email with code     | ❌            |
| POST   | `/resend-verification`     | Resend verification email  | ❌            |
| POST   | `/forgot-password`         | Request password reset     | ❌            |
| POST   | `/reset-password`          | Reset password with code   | ❌            |
| POST   | `/refresh`                 | Refresh access token       | ❌            |
| POST   | `/logout`                  | Logout user                | ❌            |
| POST   | `/check-verification-code` | Validate verification code | ❌            |

### User Management (`/api/v1/users`)

| Method | Endpoint | Description                 | Auth Required |
| ------ | -------- | --------------------------- | ------------- |
| GET    | `/me`    | Get current user profile    | ✅            |
| PUT    | `/me`    | Update current user profile | ✅            |
| DELETE | `/me`    | Delete current user account | ✅            |

### Session Management (`/api/v1/sessions`)

| Method | Endpoint        | Description                      | Auth Required |
| ------ | --------------- | -------------------------------- | ------------- |
| GET    | `/`             | Get all user sessions            | ✅            |
| DELETE | `/{session_id}` | Delete specific session          | ✅            |
| DELETE | `/`             | Delete all sessions (logout all) | ✅            |
| POST   | `/cleanup`      | Cleanup expired sessions         | ✅            |

## 📦 Dependency Management

We use **uv** for dependency management across all environments (development and production):

```bash
uv add <package>        # Add new dependency
uv add --dev <package>  # Add dev dependency
uv sync                 # Install all dependencies (dev + prod)
uv sync --no-dev        # Install only production dependencies
```

## 🛠️ Development Workflow

### Daily Commands

```bash
make dev          # Start dev server with hot-reload
make test         # Run test suite
make test-cov     # Run tests with coverage report
make format       # Auto-format code (Ruff + Black)
make lint         # Check code quality
make type-check   # Validate type hints
make check        # Run all quality checks (lint + type + test)
```

### Database Migrations

```bash
make migrate-create MESSAGE="add users table"  # Create migration
make migrate-up                                 # Apply migrations
make migrate-down                               # Rollback one migration
```

### Docker Commands

```bash
make docker-up         # Start development containers
make docker-logs       # View container logs
make docker-down       # Stop containers
make docker-prod-up    # Deploy production
```

### Adding Dependencies

```bash
# 1. Add with uv
uv add fastapi-users

# 2. Commit dependency files
git add pyproject.toml uv.lock
git commit -m "Add fastapi-users"
```

## 📁 Project Structure

```
api/
├── app/                          # Application code
│   ├── main.py                   # FastAPI app entry point
│   ├── celery_app.py             # Celery application & worker configuration
│   ├── advices/                  # Response handlers & exception handling
│   │   ├── base_response_handler.py
│   │   ├── global_exception_handler.py
│   │   └── responses.py
│   ├── config/                   # Configuration & base classes
│   │   ├── base_repositories.py  # Generic repository pattern
│   │   ├── base.py               # SQLAlchemy base model
│   │   └── settings.py           # Application settings
│   ├── db/                       # Database configuration
│   │   └── connect_db.py         # Async connection pool
│   ├── exceptions/               # Custom exceptions
│   │   └── exceptions.py
│   ├── mail/                     # Email service
│   │   ├── service/
│   │   │   └── resend_service.py # Resend API integration
│   │   └── templates/            # Email templates
│   ├── middlewares/              # HTTP middlewares
│   │   └── auth_middleware.py    # JWT validation
│   └── modules/                  # Feature modules
│       ├── user_service/         # User management module
│       │   ├── models/           # SQLAlchemy models
│       │   ├── repositories/     # Data access layer
│       │   ├── routes/           # API endpoints
│       │   ├── schema/           # Pydantic schemas
│       │   ├── services/         # Business logic
│       │   └── utils/            # Utility functions
│       ├── strategy_service/     # Strategy management & execution module
│       │   ├── controllers/      # Strategy controllers
│       │   ├── models/           # SQLAlchemy models
│       │   ├── repositories/     # Strategy repositories
│       │   ├── routes/           # Strategy API routes
│       │   ├── schema/           # Strategy Pydantic schemas
│       │   ├── services/         # Strategy business logic
│       │   └── tasks.py          # Celery background tasks
│       └── data_service/         # Data ingestion & market data module
│           ├── clients/          # API & WebSocket clients
│           ├── services/         # Data services
│           └── manager.py        # Connection manager
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration files
│   ├── env.py                    # Migration configuration
│   └── script.py.mako            # Migration template
├── tests/                        # Test suite
│   ├── conftest.py               # Root test fixtures
│   ├── test_main.py              # Main API endpoint tests
│   ├── verify_streamer.py        # Streamer verification utility
│   └── modules/                  # Module tests
│       ├── user_service/         # User service test suite
│       └── strategy_service/     # Strategy service test suite
├── docs/                         # Documentation
│   ├── DEVELOPMENT.md            # Development guide
│   ├── DEPLOYMENT.md             # Deployment instructions
│   ├── ARCHITECTURE.md           # Architecture overview
│   └── README.md                 # Docs overview
├── Dockerfile                    # Production image
├── Dockerfile.dev                # Development image
├── docker-compose.yaml           # Production compose
├── docker-compose-dev.yaml       # Development compose
├── pyproject.toml                # uv & tool configuration
├── uv.lock                       # uv lockfile (dependency lock)
└── Makefile                      # Development commands
```

## 🔧 Code Quality Tools

| Tool           | Purpose                    | Run Command       |
| -------------- | -------------------------- | ----------------- |
| **Ruff**       | Fast linting & auto-fixes  | `make lint`       |
| **Black**      | Code formatting            | `make format`     |
| **MyPy**       | Type checking              | `make type-check` |
| **Pytest**     | Testing framework          | `make test`       |
| **Pre-commit** | Automated checks on commit | Auto-runs         |

All tools are configured in `pyproject.toml` and run automatically via pre-commit hooks.

## 🧪 Testing

Our test suite ensures production reliability with comprehensive coverage:

```bash
make test              # Run all tests (76 tests)
make test-cov          # Generate coverage report (100% coverage)
pytest tests/modules/user_service/routes/ -v  # Run route tests only
```

### Test Coverage by Layer

| Layer            | Tests        | Coverage |
| ---------------- | ------------ | -------- |
| **Routes**       | 19 tests     | 100%     |
| **Services**     | 35 tests     | 100%     |
| **Repositories** | 22 tests     | 100%     |
| **Total**        | **76 tests** | **100%** |

### Test Structure

```
tests/
├── conftest.py                    # Root fixtures (DB setup)
└── modules/
    └── user_service/
        ├── conftest.py            # Module fixtures (mocks)
        ├── routes/
        │   ├── conftest.py        # Route fixtures
        │   ├── test_auth_routes.py
        │   ├── test_user_routes.py
        │   └── test_session_routes.py
        ├── services/
        │   ├── test_auth_service.py
        │   ├── test_user_service.py
        │   └── test_session_service.py
        └── repositories/
            ├── test_user_repository.py
            └── test_session_repository.py
```

### Key Testing Features

- **Async Testing**: Full pytest-asyncio support
- **Database Isolation**: Test database with Docker
- **Fixture-based Mocking**: Clean, reusable test fixtures
- **Dependency Override**: FastAPI dependency injection mocking
- **Test Environment**: Separate configuration for testing

## 🚀 Deployment

### Pre-Deployment Checklist

Before deploying to production:

```bash
# 1. Run all quality checks
make check              # Runs lint + type-check + tests

# 2. Update production secrets in .env.prod
# - Generate strong JWT secrets
# - Configure production database URL
# - Add email service credentials

# 3. Build and test production image
make docker-build
make docker-prod-up

# 4. Verify deployment
curl http://localhost:8000/health
```

### Production Configuration

Critical settings for `.env.prod`:

```env
ENV=production          # MUST be 'production'
DEBUG=False            # MUST be False for security
APP_ENV=production     # Disables test bypasses

# Generate strong secrets (DO NOT use example values)
ACCESS_TOKEN_SECRET_KEY=<use-crypto-random-64-chars>
REFRESH_TOKEN_SECRET_KEY=<use-crypto-random-64-chars>

# Production database (not localhost!)
DATABASE_URL=postgresql+asyncpg://user:pass@prod-host:5432/crypalgos

# Email service
RESEND_API_TOKEN=re_xxxxxxxxxxxxx
RESEND_FROM_EMAIL=noreply@yourdomain.com
```

### Docker Deployment

```bash
# Start production containers
make docker-prod-up

# View logs
make docker-logs

# Stop containers
make docker-down
```

### Database Migrations

```bash
# Apply migrations in production
docker-compose exec api alembic upgrade head

# Or via Makefile
make migrate-up
```

### Health Checks

The API includes health check endpoints:

- `GET /health` - Basic health check
- `GET /` - Root endpoint

### Monitoring & Logging

The application uses structured logging with different levels:

- **INFO**: User operations, authentication events
- **WARNING**: Failed lookups, invalid attempts
- **ERROR**: Email failures, service errors

Logs include:

- User identifiers (for auditing)
- IP addresses (for security)
- Timestamps (for tracking)
- Error details (for debugging)

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for detailed deployment instructions.

## ⚙️ Configuration

### Environment Files

The application uses environment-specific configuration files:

```bash
.env.dev       # Development environment
.env.test      # Testing environment
.env.prod      # Production environment
.env.example   # Template for new environments
```

### Quick Setup

1. **Development**:

   ```bash
   cp .env.example .env.dev
   # Edit .env.dev with your development settings
   make dev
   ```

2. **Testing**:

   ```bash
   cp .env.example .env.test
   # Configure test database
   ENV_FILE=.env.test APP_ENV=testing pytest
   ```

3. **Production**:
   ```bash
   cp .env.example .env.prod
   # Update with production secrets
   make docker-prod-up
   ```

### Required Configuration

```env
# Environment
ENV=production              # development, testing, or production
DEBUG=False                # Enable debug mode

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# JWT Authentication
ACCESS_TOKEN_SECRET_KEY=<generate-strong-secret>
REFRESH_TOKEN_SECRET_KEY=<generate-strong-secret>
JWT_ALGORITHMS=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_MINUTES=10080  # 7 days

# Email Service (Resend)
RESEND_API_TOKEN=<your-resend-api-key>
RESEND_FROM_EMAIL=noreply@yourdomain.com
RESEND_FROM_NAME=CrypAlgos Team
```

### Environment Selection

The app automatically selects the environment file:

```bash
# Via APP_ENV variable (recommended)
APP_ENV=production make run

# Via explicit ENV_FILE
ENV_FILE=.env.prod make run

# Docker Compose sets this automatically
make docker-prod-up  # Uses .env.prod
```

### Security Best Practices

⚠️ **Never commit these to git**:

- `.env.dev`, `.env.test`, `.env.prod`
- Any file containing secrets or API keys

✅ **Do commit**:

- `.env.example` (template with no secrets)

## 🏗️ Architecture

### Layered Architecture

The application follows a clean, layered architecture pattern:

```
┌─────────────────────────────────────┐
│         Routes (API Layer)          │  ← HTTP endpoints
├─────────────────────────────────────┤
│        Services (Business Logic)    │  ← Core functionality
├─────────────────────────────────────┤
│      Repositories (Data Access)     │  ← Database operations
├─────────────────────────────────────┤
│         Models (Entities)           │  ← SQLAlchemy models
└─────────────────────────────────────┘
```

### Key Design Patterns

1. **Repository Pattern**: Abstracts data access logic
   - Generic base repository for common operations
   - Specialized repositories for complex queries
   - Easy to mock for testing

2. **Dependency Injection**: FastAPI's built-in DI
   - Service dependencies injected via `Depends()`
   - Easy to override for testing
   - Clean separation of concerns

3. **Schema Validation**: Pydantic models
   - Request/response validation
   - Type safety at API boundaries
   - Automatic OpenAPI documentation

4. **Async/Await**: Full async support
   - AsyncSession for database
   - Async route handlers
   - Async service methods

### Authentication Flow

```
1. User Registration
   ├─> POST /auth/register
   ├─> Create user (unverified)
   ├─> Generate verification code
   └─> Send verification email

2. Email Verification
   ├─> POST /auth/verify
   ├─> Validate code & expiry
   ├─> Mark user as verified
   ├─> Create session
   └─> Return JWT tokens

3. Login
   ├─> POST /auth/login
   ├─> Validate credentials
   ├─> Create new session
   └─> Return JWT tokens

4. Protected Endpoint Access
   ├─> Authorization: Bearer <token>
   ├─> Middleware validates JWT
   ├─> Extract user_id from token
   └─> Process request
```

### Session Management

- **Multi-device support**: Track sessions per device
- **Session limits**: Configurable max sessions per user
- **Automatic cleanup**: Remove expired sessions
- **Refresh tokens**: Long-lived tokens for access renewal
- **Logout options**: Single device or all devices

## 📚 Documentation

- **[Development Guide](docs/DEVELOPMENT.md)** - Setup and coding practices
- **[Deployment Guide](docs/DEPLOYMENT.md)** - Production deployment
- **[Architecture](docs/ARCHITECTURE.md)** - System design and patterns
- **[Contributing](CONTRIBUTING.md)** - Contribution guidelines

Run `make help` to see all available commands.

## 🛠️ Development Commands

```bash
# Database management
make migrate-dev           # Run migrations in dev
make create-migration msg="your message"  # Create new migration
make downgrade-dev         # Rollback last migration

# Testing
make test                  # Run all tests
make test-verbose          # Run with detailed output
make test-coverage         # Generate coverage report

# Docker operations
make dev-up               # Start dev containers
make dev-down             # Stop dev containers
make dev-logs             # View container logs
make dev-shell            # Access container shell

# Code quality
make lint                 # Run linters
make format               # Format code
make type-check           # Run type checking
make check                # Run all quality checks
```

## 🔒 Security Best Practices

### Production Security Checklist

- ✅ **Strong Secrets**: Generate cryptographically secure keys

  ```bash
  openssl rand -hex 32  # For JWT secrets
  ```

- ✅ **HTTPS Only**: Enable SSL/TLS in production
- ✅ **Rate Limiting**: Implement rate limiting on auth endpoints
- ✅ **CORS**: Configure allowed origins properly
- ✅ **Database**: Use connection pooling and read replicas
- ✅ **Logging**: Enable structured logging with proper log levels
- ✅ **Monitoring**: Set up health checks and metrics
- ✅ **Secrets Management**: Use environment-specific secret storage

### Token Security

- Access tokens expire in 30 minutes
- Refresh tokens expire in 7 days
- Tokens are signed with HS256
- Sessions are tracked per device
- Old sessions auto-expire

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Quick checklist:

1. Fork and create a feature branch
2. Make changes following our code style
3. Run `make check` to verify quality (lint + type-check + tests)
4. Add tests for new features
5. Update documentation
6. Submit a pull request

## 📄 License

MIT License - See LICENSE file for details

## 🆘 Support

For issues and questions:

- 📝 Open an issue on GitHub
- 📚 Check documentation in `docs/`
- 💻 Run `make help` for command reference

---

**Built with ❤️ using FastAPI, PostgreSQL, and modern Python practices**
