
.PHONY: start stop logs lint format format_diff router-tests local-deps local-api local-web

PYTEST_ARGS ?=

pull:
	bash docker/pull_image.sh python:3.12-slim
	bash docker/pull_image.sh node:20-slim
	bash docker/pull_image.sh node:20-alpine
	bash docker/pull_image.sh milvusdb/milvus:v2.5.6
	bash docker/pull_image.sh neo4j:5.26
	bash docker/pull_image.sh minio/minio:RELEASE.2023-03-20T20-16-18Z
	bash docker/pull_image.sh ghcr.io/astral-sh/uv:0.7.2
	bash docker/pull_image.sh nginx:alpine
	bash docker/pull_image.sh quay.io/coreos/etcd:v3.5.5

start:
	@if [ ! -f .env ]; then \
		echo "Error: .env file not found. Please create it from .env.template"; \
		exit 1; \
	fi
	docker compose up -d

stop:
	docker compose down

logs:
	@docker logs --tail=50 api-dev
	@echo "\n\nBranch: $$(git branch --show-current)"
	@echo "Commit ID: $$(git rev-parse HEAD)"
	@echo "System: $$(uname -a)"

######################
# LINTING AND FORMATTING
######################

lint:
	uv run python -m ruff check .
	uv run python -m ruff format --check src
	uv run python -m ruff check --select I src

format:
	uv run python -m ruff format .
	uv run python -m ruff check . --fix
	uv run python -m ruff check --select I src --fix
	cd web && npm run format

router-tests:
	docker compose exec -T api uv run --group test pytest test/api $(PYTEST_ARGS)

######################
# LOCAL DEVELOPMENT (不走 Docker API 容器)
######################

local-deps:
	docker compose up -d postgres graph etcd minio milvus

local-api: local-deps
	POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi_know \
	NEO4J_URI=bolt://localhost:7687 \
	MILVUS_URI=http://localhost:19530 \
	MINIO_URI=http://localhost:9000 \
	uv run uvicorn server.main:app --host 0.0.0.0 --port 5050 --reload

local-web:
	cd web && VITE_API_URL=http://localhost:5050 pnpm run dev
