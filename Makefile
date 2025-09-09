# Makefile for Legends of the Breach

# Python interpreter
PYTHON = python3

# Virtual environment directory
VENV = venv

.PHONY: all install run clean

all: run

install: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate; pip install -r requirements.txt
	touch $(VENV)/bin/activate

run: install
	. $(VENV)/bin/activate; $(PYTHON) main.py

clean:
	rm -rf $(VENV)
	find . -name "*.pyc" -exec rm -f {} +
	find . -name "__pycache__" -exec rm -rf {} +
