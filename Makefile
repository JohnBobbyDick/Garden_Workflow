# venv layout differs: bin/ on Linux/macOS, Scripts/ on Windows
VBIN := $(if $(wildcard backend/.venv/Scripts),.venv/Scripts,.venv/bin)
PG_TEST_URL ?= postgresql+psycopg://aisw:aisw@127.0.0.1:55432/aisw_test

.PHONY: up up-mock up-ollama down clean logs smoke demo-full demo-diff demo-autofix dev-backend dev-frontend dev-worker test test-backend test-frontend test-eval test-pg e2e lint seed install mock nodes-doc api-doc docs

install:
	cd backend && uv venv -q -p 3.12 .venv && uv pip install -q --python $(VBIN)/python -e ".[dev]"
	cd frontend && npm ci

up:
	docker compose up -d --build

up-mock:
	docker compose --profile mock up -d --build

up-ollama:
	docker compose --profile ollama up -d --build

down:
	docker compose --profile mock --profile ollama down

clean:
	docker compose --profile mock --profile ollama down -v --remove-orphans

logs:
	docker compose logs -f backend worker

# end-to-end smoke on the running compose stack (mock profile): 15 findings, submission.json, webhook delivered
smoke:
	backend/$(VBIN)/python scripts/demo_stack.py --url http://localhost:$${FRONTEND_PORT:-8080}

# demo scenario §21 (steps 1–8, 10) on the running compose stack; add MODEL=qwen2.5:3b when the ollama profile is up
demo-full:
	backend/$(VBIN)/python scripts/demo_full.py --url http://localhost:$${FRONTEND_PORT:-8080} $(if $(MODEL),--model $(MODEL),--no-llm)

demo-diff:
	scripts/demo_diff.sh

demo-autofix:
	scripts/demo_autofix.sh

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
	cd backend && $(VBIN)/ruff check app tests ../scripts
	cd frontend && npx tsc -b --noEmit

mock:
	cd backend && $(VBIN)/python ../scripts/mock_services.py

nodes-doc:
	cd backend && $(VBIN)/python ../scripts/gen_nodes_doc.py

api-doc:
	cd backend && $(VBIN)/python ../scripts/gen_api_doc.py

docs: nodes-doc api-doc

seed:
	cd backend && $(VBIN)/python -m app.seed.run
