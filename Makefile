dev_deps:
	pip install -r requirements.dev.txt

install:
	pip install -e .

test:
	python -m unittest discover tests

lint:
	flake8

check: lint test

build: dev_deps
	python setup.py sdist        # builds source distribution
	python setup.py bdist_wheel  # builds wheel

release: build
	twine upload dist/*

.PHONY: deps test lint build release
