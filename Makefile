PY_FILES = main.py simulation.py pathfinder.py parser.py graph.py zone.py \
	connection.py drone.py events.py visualizers.py pygame_airlines.py weather.py

install:
	uv venv
	uv pip install flake8 mypy pygame-ce

run:
	uv run python3 main.py $(MAP)

run-pygame:
	uv run python3 main.py $(MAP) --pygame-airlines

debug:
	uv run python3 -m pdb main.py $(MAP)

lint:
	uv run flake8 $(PY_FILES)
	uv run mypy $(PY_FILES) --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	uv run flake8 $(PY_FILES)
	uv run mypy $(PY_FILES) --strict

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -rf .venv