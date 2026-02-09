# Documentation Index

Welcome to the CrypAlgos API documentation! This guide will help you find what you need.

## 📚 Documentation Structure

### For Developers

- **[Development Guide](DEVELOPMENT.md)** - Start here!
  - Setup instructions (Poetry, Docker, Database)
  - Daily workflow (running, testing, linting)
  - Adding features (routes, services, repositories)
  - Testing guide (76 tests, 100% coverage)
  - Code style standards (Ruff, Black, MyPy)

- **[Architecture Overview](ARCHITECTURE.md)** - System design
  - Layered architecture (Routes → Services → Repositories → Models)
  - Design patterns (Repository, DI, Generic Base Repository)
  - Authentication flow (JWT, sessions, email verification)
  - Database design (User, Session, Subscription models)
  - Security practices (JWT middleware, password hashing)

### For DevOps/Deployment

- **[Deployment Guide](DEPLOYMENT.md)** - Production deployment
  - Docker deployment
  - Cloud platforms (AWS, GCP, Azure)
  - Database management
  - Monitoring
  - Scaling strategies

### For Contributors

- **[Contributing Guidelines](../CONTRIBUTING.md)** - How to contribute
  - Development workflow
  - Code standards
  - Pull request process
  - Testing requirements

## 🚀 Quick Links

### Getting Started
1. [Setup Development Environment](DEVELOPMENT.md#setup)
2. [Run Your First Test](DEVELOPMENT.md#testing)
3. [Understand the Architecture](ARCHITECTURE.md)

### Common Tasks
- [Add a New Feature](DEVELOPMENT.md#adding-features)
- [Create Database Migration](DEVELOPMENT.md#database-migrations)
- [Add Dependencies](DEVELOPMENT.md#dependency-management)
- [Deploy to Production](DEPLOYMENT.md#production-deployment-with-docker)

### Troubleshooting
- [Development Issues](DEVELOPMENT.md#common-issues)
- [Deployment Issues](DEPLOYMENT.md#troubleshooting)

## 📖 External Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Pytest Documentation](https://docs.pytest.org/)

## 🔍 Finding What You Need

### "I want to..."

| Task | See |
|------|-----|
| Set up my development environment | [Development Guide - Setup](DEVELOPMENT.md#setup) |
| Understand the codebase | [Architecture Overview](ARCHITECTURE.md) |
| Add a new API endpoint | [Development Guide - Adding Features](DEVELOPMENT.md#adding-features) |
| Deploy to production | [Deployment Guide](DEPLOYMENT.md) |
| Contribute code | [Contributing Guidelines](../CONTRIBUTING.md) |
| Run tests | [Development Guide - Testing](DEVELOPMENT.md#testing) |
| Manage database | [Development Guide - Migrations](DEVELOPMENT.md#database-migrations) |
| Scale the application | [Deployment Guide - Scaling](DEPLOYMENT.md#scaling) |

## 📝 Documentation Standards

When writing documentation:

1. **Be clear and concise**
   - Use simple language
   - Provide examples
   - Include code snippets

2. **Keep it up to date**
   - Update docs with code changes
   - Remove outdated information
   - Add migration guides for breaking changes

3. **Use proper formatting**
   - Headers for sections
   - Code blocks for commands
   - Tables for comparisons
   - Lists for steps

## 🤝 Need Help?

If you can't find what you're looking for:

1. Check the [FAQ](https://github.com/crypalgos/api/wiki/FAQ) (if available)
2. Search [existing issues](https://github.com/crypalgos/api/issues)
3. Ask in [Discussions](https://github.com/crypalgos/api/discussions)
4. Open a new issue with the `documentation` label

## 📅 Documentation Updates

This documentation is maintained alongside the codebase. Last major update: November 2025.

For the latest changes, see the [CHANGELOG](../CHANGELOG.md) (if available).
