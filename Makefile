REGISTRY  := ghcr.io/ptinkler
IMAGE_APP := $(REGISTRY)/cyno-studio
IMAGE_NGX := $(REGISTRY)/cyno-studio-nginx
TAG       := latest

.PHONY: lock build push tag dev dev-api dev-frontend lint format test gen-api hooks vpn-restart vpn-status vpn-logs db-migrate db-upgrade db-downgrade db-history

build:
	docker build -t $(IMAGE_APP):$(TAG) .
	docker build -f nginx/Dockerfile -t $(IMAGE_NGX):$(TAG) .

push: build
	docker push $(IMAGE_APP):$(TAG)
	docker push $(IMAGE_NGX):$(TAG)

tag:
	$(eval LATEST := $(shell git tag --sort=-version:refname | head -1 || echo "v0.0.0"))
	$(eval PATCH  := $(shell echo $(LATEST) | awk -F. '{print $$3+1}'))
	$(eval NEXT   := $(shell echo $(LATEST) | awk -F. -v p=$(PATCH) '{print $$1"."$$2"."p}'))
	git tag $(NEXT) && git push origin $(NEXT)

dev-api:
	.venv/bin/python -m uvicorn web.api:app --app-dir src/py --reload --reload-dir src/py --port 5000

dev-frontend:
	cd src/js && npm run dev

dev:
	$(MAKE) -j2 dev-api dev-frontend

# Code standards: ruff + basedpyright (Python) and ESLint + Prettier + vue-tsc (frontend). CI runs `lint`.
lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/basedpyright
	cd src/js && npm run lint && npm run format:check && npm run typecheck

format:
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .
	cd src/js && npm run lint:fix && npm run format

# Run the lint checks on every commit (.githooks/pre-commit runs .pre-commit-config.yaml;
# from git for Windows it runs them inside WSL)
hooks:
	git config core.hooksPath .githooks

test:
	.venv/bin/python -m pytest -q
	cd src/js && npm test

# Regenerate the frontend's API types (src/js/src/api/schema.d.ts) from the backend's OpenAPI schema.
# CI runs this too and fails if the committed file is stale.
PY ?= .venv/bin/python
gen-api:
	@tmp=$$(mktemp) && data=$$(mktemp -d) \
		&& PYTHONPATH=src/py CYNO_DATA_DIR=$$data $(PY) -m scripts.export_openapi $$tmp >/dev/null \
		&& (cd src/js && npm run --silent gen:api -- $$tmp); \
		status=$$?; rm -rf $$tmp $$data; exit $$status

# Pollo model maintenance scripts (src/py is put on the path for you). Pass options with ARGS, e.g.
#   make audit-models ARGS="--key sk-..."
# Re-resolve uv.lock (add --upgrade to move everything forward)
lock:
	uv lock

audit-models:
	PYTHONPATH=src/py .venv/bin/python -m scripts.audit_pollo_models $(ARGS)

probe-models:
	PYTHONPATH=src/py .venv/bin/python -m scripts.probe_pollo_models $(ARGS)

vpn-restart:
	docker compose --profile vpn restart gluetun

vpn-status:
	docker compose --profile vpn exec gluetun cat /tmp/gluetun/ip
	@echo "---"
	docker compose --profile vpn exec gluetun wget -qO- ifconfig.me 2>/dev/null || echo "(could not reach ifconfig.me)"

vpn-logs:
	docker compose --profile vpn logs gluetun --tail 30

# ── Database migrations (Alembic) ──────────────────
db-migrate:  ## Generate a new migration: make db-migrate msg="add foo column"
	alembic revision --autogenerate -m "$(msg)"

db-upgrade:  ## Apply all pending migrations
	alembic upgrade head

db-downgrade:  ## Revert the last migration
	alembic downgrade -1

db-history:  ## Show migration history
	alembic history --verbose
