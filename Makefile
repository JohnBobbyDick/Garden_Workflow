PY := backend/.venv/bin/python
PYTEST := backend/.venv/bin/pytest

.PHONY: up down dev-backend dev-frontend dev-worker test test-backend test-frontend test-eval test-pg e2e lint seed install

install:
	cd backend && uv venv -q -p 3.12 .venv && uv pip install -q --python .venv/bin/python -e ".[dev]"
	cd frontend && npm ci

up:
	docker compose up -d --build

down:
	docker compose down

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-worker:
	cd backend && .venv/bin/python -m app.engine.worker

dev-frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && .venv/bin/pytest -q

test-frontend:
	cd frontend && npx vitest run --passWithNoTests

test-eval:
	cd backend && .venv/bin/pytest -q -m eval -s tests/eval

test-pg:
	cd backend && .venv/bin/pytest -q -m postgres

e2e:
	cd frontend && npx playwright test

lint:
	cd backend && .venv/bin/ruff check app tests
	cd frontend && npx tsc -b --noEmit

seed:
	cd backend && .venv/bin/python -m app.seed.run
