PY_FILES = main.py simulation.py pathfinder.py parser.py graph.py zone.py \
	connection.py drone.py events.py visualizers.py pygame_standard.py \
	pygame_airlines.py pygame_common.py weather.py config.py
TEST_DIR = tests

.PHONY: install hooks run run-pygame run-pygame-airlines debug lint \
	lint-strict test coverage check clean

install:
	uv sync --locked

hooks:
	git config core.hooksPath .githooks

run:
	uv run --locked python3 main.py $(MAP)

run-pygame:
	uv run --locked python3 main.py $(MAP) --pygame

run-pygame-airlines:
	uv run --locked python3 main.py $(MAP) --pygame-airlines

debug:
	uv run --locked python3 -m pdb main.py $(MAP)

lint:
	uv run --locked flake8 $(PY_FILES) $(TEST_DIR)
	uv run --locked mypy $(PY_FILES) $(TEST_DIR) --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	uv run --locked flake8 $(PY_FILES) $(TEST_DIR)
	uv run --locked mypy $(PY_FILES) $(TEST_DIR) --strict

test:
	uv run --locked pytest

coverage:
	uv run --locked pytest --cov --cov-report=term-missing

check: lint-strict test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache htmlcov
	rm -f .coverage .coverage.*
	rm -rf .venv
