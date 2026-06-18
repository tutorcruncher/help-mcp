.PHONY: install install-dev test test-cov lint type-check format clean run-dev help

# Show available targets
help:
	@grep -E '^[a-zA-Z_-]+:.*?# .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?# "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  # Install runtime dependencies
	uv sync --no-dev

install-dev:  # Install all dependencies + pre-commit hooks
	uv sync
	uv run pre-commit install

test:  # Run tests
	uv run pytest -n auto

test-cov:  # Run tests with coverage
	uv run pytest -n auto --cov=app --cov-report=term-missing

lint:  # Lint and type-check
	uv run ruff check .
	uv run ruff format --check .
	uv run ty check .

type-check:  # Type check code
	uv run ty check .

format:  # Auto-fix and format
	uv run ruff check --fix .
	uv run ruff format .
	uv run ty check .

run-dev:  # Run the MCP server (binds 0.0.0.0:$PORT, default 8000)
	uv run python -m app.server

clean:  # Clean cache files
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
