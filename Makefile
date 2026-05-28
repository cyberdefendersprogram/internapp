# internapp – development workflow
# Usage: make <target>

# ── Config ────────────────────────────────────────────────────────────────────
VM_IP       := $(shell grep ^VM_IP .env 2>/dev/null | cut -d= -f2)
VM_PASSWORD := $(shell grep ^VM_PASSWORD .env 2>/dev/null | cut -d= -f2)
SERVER_DIR  := /opt/internapp
PYTHON      := .venv/bin/python
PYTEST      := .venv/bin/pytest
UVICORN     := .venv/bin/uvicorn
RUFF        := .venv/bin/ruff
SSH_CMD     := sshpass -p '$(VM_PASSWORD)' ssh -o StrictHostKeyChecking=no root@$(VM_IP)

.PHONY: help dev docker-dev test lint fmt seed \
        deploy logs ssh health restart db-reset

# ── Default ───────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  make dev          Run app locally with hot-reload (port 8001)"
	@echo "  make docker-dev   Run app locally in Docker"
	@echo ""
	@echo "  make test         Run test suite"
	@echo "  make lint         Check code style (ruff)"
	@echo "  make fmt          Auto-format code (ruff)"
	@echo ""
	@echo "  make deploy       Push to main → CI builds image → server auto-deploys"
	@echo "  make logs         Tail live server logs"
	@echo "  make ssh          Open shell on server"
	@echo "  make health       Check server health endpoint"
	@echo "  make restart      Restart containers on server"
	@echo "  make db-reset     Wipe SQLite on server (resets sessions/cache)"
	@echo "  make seed         Seed Google Sheet structure (all tabs + headers)"
	@echo ""

# ── Local dev ─────────────────────────────────────────────────────────────────
dev:
	$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8001

docker-dev:
	docker compose -f docker-compose.dev.yml up --build

# ── Testing & linting ─────────────────────────────────────────────────────────
test:
	$(PYTEST) tests/ -q

lint:
	$(RUFF) check app/ tests/
	$(RUFF) format --check app/ tests/

fmt:
	$(RUFF) format app/ tests/
	$(RUFF) check --fix app/ tests/

# ── Seeding ───────────────────────────────────────────────────────────────────
seed:
	GOOGLE_SERVICE_ACCOUNT_PATH=.secrets/service-account.json \
	$(PYTHON) scripts/seed_sheets.py --create-structure

# ── Server ────────────────────────────────────────────────────────────────────
deploy:
	git push origin main
	@echo ""
	@echo "  CI is building and deploying. Watch progress at:"
	@echo "  https://github.com/$(shell git remote get-url origin 2>/dev/null | sed 's/.*github.com[:/]\(.*\)\.git/\1/')/actions"
	@echo ""

logs:
	$(SSH_CMD) "cd $(SERVER_DIR) && docker compose logs -f --tail=50"

ssh:
	sshpass -p '$(VM_PASSWORD)' ssh -o StrictHostKeyChecking=no root@$(VM_IP)

health:
	@curl -s http://$(VM_IP):8001/health | $(PYTHON) -m json.tool

restart:
	$(SSH_CMD) "cd $(SERVER_DIR) && docker compose restart"
	@echo "Restarted."

db-reset:
	@echo "Wiping SQLite on server (sessions + cache)..."
	$(SSH_CMD) "docker exec \$$(docker ps --format '{{.Names}}' | grep internapp) rm -f /var/lib/internapp/app.db && docker compose -f $(SERVER_DIR)/docker-compose.yml restart"
	@echo "Done. DB will reinitialize on next request."
