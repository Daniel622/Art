.PHONY: run test

run:
	python3 server.py

test:
	python3 -m unittest discover -s tests
