# Polymarket Trading Bot - Local Development & Testing
# Run these commands locally for CI/CD without GitHub Actions

.PHONY: all help install test test-cov lint format check clean run-paper build push

# Default target
all: check

help: ## Show this help
	@echo "Polymarket Trading Bot - Available Commands:"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Quick start: make install && make check && make test"

# Installation
install: ## Install dependencies and dev tools
	pip install --upgrade pip
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-cov black isort flake8 mypy pre-commit
	pre-commit install

install-dev: ## Install with all dev dependencies
	pip install -e ".[dev]"

# Testing
test: ## Run all tests
	python -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	python -m pytest tests/ -v --tb=short --cov=src --cov-report=html --cov-report=term

test-watch: ## Run tests on file changes (requires pytest-watch)
	pytest-watch tests/ -- -v --tb=short

# Code quality
type-check: ## Run mypy type checking
	mypy src/ --ignore-missing-imports --warn-unused-configs

lint: ## Run flake8 linter
	flake8 src/ tests/ --max-line-length=100 --ignore=E203,W503 --exclude=venv,.venv

format: ## Format code with black and isort
	black src/ tests/ scripts/
	isort src/ tests/ scripts/

format-check: ## Check formatting without modifying files
	black --check src/ tests/ scripts/
	isort --check-only src/ tests/ scripts/

security: ## Security scan with bandit (optional)
	bandit -r src/ -f json -o bandit-report.json || true
	@echo "Security scan complete"

# Combined checks
check: format-check lint type-check ## Run all checks (format, lint, types)
	@echo "✓ All checks passed"

# Running the bot
run-paper: ## Run one paper trade
	python scripts/btc_15m_monitor_v2.py --dry-run --duration 300

run-monitor: ## Run continuous monitoring (paper trading)
	python scripts/btc_15m_monitor_v2.py --monitor --interval 300

run-dashboard: ## Start metrics dashboard
	@echo "Metrics available at http://localhost:8080/metrics"
	python -c "from src.utils.monitoring import get_metrics; get_metrics(8080)"

# Docker commands
docker-build: ## Build Docker image
	docker build -t polymarket-bot:latest .

docker-run: ## Run Docker container
	docker run -it --rm \
		-v $(PWD)/data:/app/data \
		--env-file .env \
		polymarket-bot:latest

docker-compose-up: ## Start full stack with Docker Compose
	docker-compose up -d

docker-compose-down: ## Stop full stack
	docker-compose down

docker-compose-logs: ## View logs
	docker-compose logs -f bot

# Database
db-init: ## Initialize database
	mkdir -p data/db
	python -c "from src.utils.db_persistence import TradingDatabase; TradingDatabase()"

db-reset: ## Reset database (WARNING: Deletes all data)
	rm -f data/trading.db
	$(MAKE) db-init

# Maintenance
clean: ## Clean up generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -f data/logs/*.log

# Git hooks
pre-commit-install: ## Install pre-commit hooks
	pre-commit install
	@echo "Pre-commit hooks installed"

pre-commit-run: ## Run pre-commit on all files
	pre-commit run --all-files

# Deployment (manual)
push: ## Push to GitHub
	git push origin master

# Full validation (local CI)
ci: clean check test-cov ## Full CI pipeline (runs all checks and tests)
	@echo "✓ Local CI complete"

# Benchmark
benchmark: ## Run performance benchmarks (optional)
	@echo "Running benchmarks..."
	python scripts/
