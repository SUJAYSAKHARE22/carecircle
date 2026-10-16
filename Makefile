.PHONY: install test lint demo client-demo
install:
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
test:
	pytest -q
lint:
	ruff check src tests
demo:
	python -m carecircle serve --demo
client-demo:
	python scripts/mcp_client_demo.py
