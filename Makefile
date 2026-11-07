.PHONY: install migrate downgrade test lint dev down logs clean help

install:
	cd backend && pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install

migrate:
	cd backend && alembic upgrade head

downgrade:
	cd backend && alembic downgrade -1

test:
	cd backend && pytest -v --asyncio-mode=auto

lint:
	cd backend && ruff check .
	cd backend && ruff format --check .
	cd frontend && npm run lint

format:
	cd backend && ruff format .
	cd backend && ruff check --fix .

dev:
	docker-compose up --build

down:
	docker-compose down

logs:
	docker-compose logs -f

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf backend/.pytest_cache backend/.ruff_cache
	docker-compose down -v

help:
	@echo "Available targets:"
	@echo "  make install       - Install Python and Node dependencies"
	@echo "  make migrate       - Run Alembic migrations (upgrade)"
	@echo "  make downgrade     - Rollback last Alembic migration"
	@echo "  make test          - Run pytest"
	@echo "  make lint          - Check code style (ruff check + ruff format --check)"
	@echo "  make format        - Format code with ruff and fix lint issues"
	@echo "  make dev           - Start all services with docker-compose"
	@echo "  make down          - Stop all services"
	@echo "  make logs          - Tail service logs"
	@echo "  make clean         - Clean build artifacts, cache, and containers"
