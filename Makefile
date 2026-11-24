PYTHON ?= python3
BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv
BIN := $(abspath $(VENV))/bin

.PHONY: setup setup-backend setup-frontend db migrate dev dev-backend dev-frontend test lint

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

test: db
	cd $(BACKEND) && $(BIN)/pytest -rs --cov --cov-report=term-missing

lint:
	cd $(BACKEND) && $(BIN)/ruff check . && $(BIN)/ruff format --check . && $(BIN)/mypy app tests
	cd $(FRONTEND) && npm run lint
