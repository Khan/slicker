deps:
	pip install -r requirements.txt

test:
	python -m unittest discover

lint:
	flake8
