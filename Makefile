.PHONY: sis08-first-slice-emit sis08-first-slice-cocotb sis08-first-slice-test

PYTHON ?= python3

sis08-first-slice-emit:
	$(PYTHON) tools/sos-codegen/sis08_first_slice.py

sis08-first-slice-test: sis08-first-slice-emit
	$(PYTHON) -m pytest tools/sos-codegen/tests/test_sis08_first_slice.py
	@if command -v cocotb-config >/dev/null 2>&1; then \
		$(MAKE) -C tb/sis08_first_slice; \
	else \
		echo "cocotb-config not found; skipping SIS-08B RTL cocotb simulation"; \
	fi

sis08-first-slice-cocotb:
	$(MAKE) -C tb/sis08_first_slice
