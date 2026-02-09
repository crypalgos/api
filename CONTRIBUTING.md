# Contributing to CrypAlgos API

Thank you for your interest in contributing! This guide will help you get started.

## Quick Start

```bash
# Fork and clone
git clone https://github.com/yourusername/crypalgos.git
cd crypalgos/api

# Setup
make setup

# Verify everything works
make check
```

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/your-feature-name
```

Use these prefixes:

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation
- `refactor/` - Code refactoring
- `test/` - Test additions
- `chore/` - Maintenance tasks

### 2. Make Changes

Follow our coding standards (see below).

### 3. Write Tests

All new code must have tests:

```python
# tests/test_your_feature.py
def test_your_feature():
    \"\"\"Test description.\"\"\"
    result = your_function()
    assert result == expected
```

### 4. Run Quality Checks

```bash
# Must pass all checks
make check

# This runs:
# - Linting (Ruff)
# - Type checking (MyPy)
# - Tests (Pytest)
```

### 5. Commit Changes

```bash
git add .
git commit -m \"feat: add new feature\"
```

Commit message format:

```
<type>: <description>

[optional body]
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### 6. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Code Standards

### Style Guide

**Follow PEP 8** - Our tools enforce this automatically.

**Type Hints Required**

```python
# Good ✅
def process_data(items: list[str]) -> dict[str, int]:
    return {item: len(item) for item in items}

# Bad ❌
def process_data(items):
    return {item: len(item) for item in items}
```

**Docstrings Required**

```python
def complex_function(param: str) -> Result:
    \"\"\"
    Brief description of what this does.

    Args:
        param: Description of parameter

    Returns:
        Description of return value

    Raises:
        ValueError: When param is invalid
    \"\"\"
    pass
```

### Naming Conventions

```python
# Variables and functions: snake_case
user_count = 10
def get_user_data(): pass

# Classes: PascalCase
class UserService: pass

# Constants: UPPER_SNAKE_CASE
MAX_RETRIES = 3

# Private: _prefix
def _internal_helper(): pass
```

### Import Order

```python
# 1. Standard library
import os
from typing import Any

# 2. Third-party
from fastapi import FastAPI
from sqlalchemy import select

# 3. Local
from app.models import User
from app.services import UserService
```

## Testing Guidelines

### Test Structure

```
tests/
├── unit/              # Fast, isolated tests
├── integration/       # Tests with database
└── e2e/              # Full API tests
```

### Writing Good Tests

```python
# Good test ✅
def test_create_user_with_valid_data():
    \"\"\"Test user creation with valid input.\"\"\"
    user = create_user(\"john@example.com\", \"password123\")
    assert user.email == \"john@example.com\"
    assert user.id is not None

# Bad test ❌
def test_user():
    user = create_user(\"john@example.com\", \"password123\")
    assert user
```

### Test Coverage

- Aim for **>80% coverage**
- All new features must have tests
- Bug fixes should include regression tests

Check coverage:

```bash
make test-cov
open htmlcov/index.html
```

## Pull Request Process

### Before Submitting

- [ ] All tests pass (`make check`)
- [ ] Code is formatted (`make format`)
- [ ] Added tests for new features
- [ ] Updated documentation if needed
- [ ] Commit messages follow convention
- [ ] No merge conflicts

### PR Description Template

```markdown
## Description

Brief description of changes

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing

How was this tested?

## Checklist

- [ ] Tests pass
- [ ] Code formatted
- [ ] Documentation updated
```

### Review Process

1. Create PR with clear description
2. Wait for CI checks to pass
3. Address reviewer feedback
4. Get approval from maintainer
5. Squash and merge

## Adding Dependencies

```bash
# Add dependency
poetry add <package>

# Add dev dependency
poetry add --group dev <package>

# IMPORTANT: Export to requirements.txt
make freeze

# Commit all dependency files
git add pyproject.toml uv.lock
git commit -m \"deps: add <package>\"
```

## Common Tasks

### Running Tests

```bash
make test              # All tests
make test-cov          # With coverage
pytest tests/test_file.py -v  # Specific file
pytest -k test_name    # Specific test
```

### Database Migrations

```bash
# Create migration
make migrate-create MESSAGE=\"description\"

# Apply migrations
make migrate-up

# Review migration file before committing!
```

### Debugging

```bash
# Run with debugger
python -m debugpy --listen 5678 --wait-for-client -m fastapi dev app/main.py

# Or add breakpoint in code
breakpoint()
```

## Documentation

Update documentation when you:

- Add new features
- Change APIs
- Modify deployment process
- Update dependencies

Documentation locations:

- API docs: Auto-generated by FastAPI
- Code docs: Docstrings in code
- Guides: `docs/` directory
- README: High-level overview

## Getting Help

- **Questions**: Open a GitHub Discussion
- **Bugs**: Open an Issue with reproduction steps
- **Features**: Open an Issue with use case description
- **Chat**: Join our Discord/Slack (if available)

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Focus on constructive feedback
- Follow project guidelines

## Recognition

Contributors are recognized in:

- README.md contributors section
- Release notes
- GitHub contributors page

Thank you for contributing! 🎉
