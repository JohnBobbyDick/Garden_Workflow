# venv layout differs: bin/ on Linux/macOS, Scripts/ on Windows
VBIN := $(if $(wildcard backend/.venv/Scripts),.venv/Scripts,.venv/bin)
PG_TEST_URL ?= postgresql+psycopg://aisw:aisw@127.0.0.1:55432/aisw_test

.PHONY: up down dev-backend dev-frontend dev-worker test test-backend test-frontend test-eval test-pg e2e lint seed install mock nodes-doc

install:
	cd backend && uv venv -q -p 3.12 .venv && uv pip install -q --python $(VBIN)/python -e ".[dev]"
	cd frontend && npm ci

up:
	docker compose up -d --build

down:
	docker compose down

dev-backend:
	cd backend && $(VBIN)/alembic upgrade head && APP_INPROCESS_WORKER=true $(VBIN)/uvicorn app.main:app --reload --port 8000

dev-worker:
	cd backend && $(VBIN)/python -m app.engine.worker

dev-frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && $(VBIN)/pytest -q

test-frontend:
	cd frontend && npx vitest run --passWithNoTests

test-eval:
	cd backend && $(VBIN)/pytest -q -m eval -s tests/eval

test-pg:
	docker run -d --rm --name aisw-pg-test -e POSTGRES_USER=aisw -e POSTGRES_PASSWORD=aisw -e POSTGRES_DB=aisw_test -p 127.0.0.1:55432:5432 postgres:16-alpine
	until docker exec aisw-pg-test pg_isready -U aisw >/dev/null 2>&1; do sleep 1; done; sleep 2
	cd backend && APP_TEST_DATABASE_URL=$(PG_TEST_URL) $(VBIN)/pytest -q -m postgres tests/integration; status=$$?; docker stop aisw-pg-test; exit $$status

e2e:
	cd frontend && npx playwright test

lint:
	cd backend && $(VBIN)/ruff check app tests
	cd frontend && npx tsc -b --noEmit

mock:
	cd backend && $(VBIN)/python ../scripts/mock_services.py

nodes-doc:
	cd backend && $(VBIN)/python ../scripts/gen_nodes_doc.py

seed:
	cd backend && $(VBIN)/python -m app.seed.run
