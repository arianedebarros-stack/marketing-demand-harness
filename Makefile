PYTHON ?= python3
BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv
BIN := $(abspath $(VENV))/bin

.PHONY: setup setup-backend setup-frontend db migrate dev dev-backend dev-frontend test test-frontend test-backend lint llm-smoke

setup: setup-backend setup-frontend

setup-backend:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e "$(BACKEND)[dev]"

setup-frontend:
	cd $(FRONTEND) && npm install

db:
	docker compose up -d --wait db

migrate:
	cd $(BACKEND) && $(BIN)/alembic upgrade head

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND) && $(BIN)/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd $(FRONTEND) && npm run dev -- --port 3000

# O frontend roda antes, para a última linha continuar sendo "Testes pulados: N" do pytest (D35).
test: test-frontend test-backend

test-frontend:
	cd $(FRONTEND) && npm test

test-backend: db
	cd $(BACKEND) && $(BIN)/pytest -rs --cov --cov-report=term-missing

lint:
	cd $(BACKEND) && $(BIN)/ruff check . && $(BIN)/ruff format --check . && $(BIN)/mypy app tests
	cd $(FRONTEND) && npm run lint && npm run typecheck

# Rodada manual com o LLM real (T16): usa ANTHROPIC_API_KEY e LLM_MODEL do .env, sem fallback.
# Uso: make llm-smoke   ou   make llm-smoke MSG="Faz uma arte da Ferjá para sexta"
llm-smoke:
	cd $(BACKEND) && $(BIN)/python -m app.cli.llm_smoke "$(MSG)"
