.PHONY: setup dev docker-up docker-down docker-prod-up test test-cov format lint type-check check migrate-create migrate-up migrate-down

setup:
	uv sync

dev:
	uv run fastapi dev app/main.py

docker-up:
	docker compose -f docker-compose-dev.yaml up --build

docker-down:
	docker compose -f docker-compose-dev.yaml down

docker-prod-up:
	docker compose -f docker-compose.yaml up --build -d

test:
	PYTHONPATH=. uv run pytest

test-cov:
	PYTHONPATH=. uv run pytest --cov=app --cov-report=term-missing

format:
	uv run ruff format . && uv run black .

lint:
	uv run ruff check .

type-check:
	uv run mypy .

check: lint type-check test

migrate-create:
	uv run alembic revision --autogenerate -m "$(MESSAGE)"

migrate-up:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade -1
