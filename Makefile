PYTHON ?= python
VERIFY_PATH ?= artifacts/sanity_output.json

.PHONY: sanity test

sanity:
	$(PYTHON) -m app.cli sanity
	$(PYTHON) scripts/verify_output.py $(VERIFY_PATH)

test:
	$(PYTHON) scripts/smoke_test.py
