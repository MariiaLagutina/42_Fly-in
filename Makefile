# Every Python file that Git tracks, or would track once added, found
# recursively. Production sources are those outside tests/, so a module that
# is added or moved is checked without editing this file.
ALL_PY := $(wildcard $(shell git ls-files --cached --others \
	--exclude-standard -- '*.py'))
PY_FILES := $(filter-out tests/%,$(ALL_PY))
TEST_DIR = tests

# Run mypy with the given options on all sources, then fail unless it
# checked every discovered file.
define mypy_all
	@out=$$(uv run --locked mypy $(PY_FILES) $(TEST_DIR) $(1)); \
	status=$$?; echo "$$out"; [ $$status -eq 0 ] || exit $$status; \
	echo "$$out" | grep -q " in $(words $(ALL_PY)) source files" || { \
		echo "mypy did not check all $(words $(ALL_PY)) Python files."; \
		exit 1; }
endef

.PHONY: install hooks run run-pygame run-pygame-airlines debug check-sources \
	lint lint-strict test coverage check benchmark clean

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

check-sources:
	@test -n "$(PY_FILES)" || { \
		echo "No production Python files found; is this a Git checkout?"; \
		exit 1; }
	@echo "Checking $(words $(PY_FILES)) production and \
	$(words $(filter tests/%,$(ALL_PY))) test Python files."

lint: check-sources
	uv run --locked flake8 $(PY_FILES) $(TEST_DIR)
	$(call mypy_all,--warn-return-any --warn-unused-ignores \
		--ignore-missing-imports --disallow-untyped-defs --check-untyped-defs)

lint-strict: check-sources
	uv run --locked flake8 $(PY_FILES) $(TEST_DIR)
	$(call mypy_all,--strict)

test:
	uv run --locked pytest

coverage:
	uv run --locked pytest --cov --cov-report=term-missing

check: lint-strict test

# The performance benchmark, run by hand and never part of `check`; options
# go in ARGS, e.g. make benchmark ARGS="--experiment E2".
benchmark:
	uv run --locked python -m benchmarks.run $(ARGS)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache htmlcov
	rm -f .coverage .coverage.*
	rm -rf .venv
