PY_FILES = main.py simulaton.py pathfinder.py parser.py graph.py zone.py \
	connection.py drone.py events.py visualizers.py pygame_airlines.py

install:
	pip install flake8 mypy pygame

run:
	python main.py $(MAP)

debug:
	python -m pdb main.py $(MAP)

lint:
	flake8 $(PY_FILES)
	mypy $(PY_FILES) --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	flake8 $(PY_FILES)
	mypy $(PY_FILES) --strict

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -name "*.pyc" -delete
