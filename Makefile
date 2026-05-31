.PHONY: setup extract clean help
.DEFAULT_GOAL := help

VENV := .venv
PY   := $(VENV)/bin/python

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the local venv and install (optional) deps from requirements.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	@echo "venv ready at $(VENV) (gitignored). Note: the extractor needs no third-party deps."

extract:  ## Pull the latest data from the TMDSAS public Power BI report into data/
	python3 src/extract_tmdsas.py

clean:  ## Remove the local venv and Python caches
	rm -rf $(VENV) **/__pycache__ __pycache__
