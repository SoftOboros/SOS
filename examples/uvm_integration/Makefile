# SPDX-License-Identifier: MIT
#
# SOS-08-F wave-2 acceptance gate (e) — worked-example build/run rules.
#
# Targets:
#   make regen          — regenerate sos_uvm_seq_pkg.sv from rtos_kernel.scxml
#                          using the SOS-08-F walker (writes into tb/).
#   make compile-<sim>  — compile the testbench under one of the supported
#                          simulators (questa, vcs, xcelium, riviera).
#   make sim-golden     — compile + run the golden vector (expect 0 errors).
#   make sim-violation  — compile + run the violation vector (expect ≥1
#                          chart-vocabulary `uvm_error` per acceptance
#                          gate (f)).
#   make clean          — remove the work directory.
#
# Simulator selection: `make SIM=questa sim-golden` or override with
# the per-tool target. Default SIM=questa.
#
# Notes:
#   * The Makefile is a *recipe template* — most enterprise UVM shops
#     already have site-specific simulator wrappers; the rules below
#     show the canonical command-line shape per vendor.
#   * No simulator is bundled. Acceptance gate (e) is satisfied by the
#     artifact set being able to elaborate + run on any UVM 1.2-capable
#     simulator; vendor binaries are customer-owned.
#   * UVM 2.0 cross-runtime smoke is a separate CI job per SOS-08-F §15
#     wave-2 carry-forward ("UVM 2.0 cross-runtime smoke test").

REPO_ROOT       := $(abspath $(CURDIR)/../..)
CHART           := $(REPO_ROOT)/rtos_kernel.scxml
CODEGEN         := $(REPO_ROOT)/tools/sos-codegen/main.py
WORK            := work
SIM             ?= questa
UVM_TESTNAME    ?= sos_kernel_test
TOP             := sos_kernel_tb_top

# File list — order matters: package first, then customer scaffolding.
SOS_PKG_SV      := tb/sos_uvm_seq_pkg.sv
SV_SOURCES      := \
    $(SOS_PKG_SV) \
    rtl/sos_kernel_dut.sv \
    tb/sos_kernel_if.sv \
    tb/sos_kernel_agent.sv \
    tb/sos_kernel_scoreboard.sv \
    tb/sos_kernel_env.sv \
    tb/sos_kernel_test.sv \
    tb/sos_kernel_tb_top.sv

.PHONY: all regen compile sim-golden sim-violation clean help

all: help

help:
	@echo "SOS-08-F wave-2 acceptance gate (e) example flow"
	@echo "  make regen           — regenerate tb/sos_uvm_seq_pkg.sv from chart"
	@echo "  make SIM=<sim> sim-golden     — run golden vector (expect pass)"
	@echo "  make SIM=<sim> sim-violation  — run violation vector (expect chart-vocab error)"
	@echo "  make clean           — remove $(WORK)/"
	@echo ""
	@echo "Supported SIM= values: questa, vcs, xcelium, riviera"

# Regenerate the SOS-emitted package from the chart. The walker writes
# uvm/<chart>/sos_uvm_seq_pkg.sv plus .svh and the integration example;
# this rule copies the .sv + .svh into tb/ for the testbench to consume.
regen:
	mkdir -p $(WORK)/regen
	python3 $(CODEGEN) --target sos-08-f --chart $(CHART) --out $(WORK)/regen
	cp $(WORK)/regen/uvm/rtos_kernel/sos_uvm_seq_pkg.sv  tb/sos_uvm_seq_pkg.sv
	cp $(WORK)/regen/uvm/rtos_kernel/sos_uvm_seq_pkg.svh tb/sos_uvm_seq_pkg.svh
	@echo "regenerated tb/sos_uvm_seq_pkg.sv from $(CHART)"

# --- Questa / Riviera-PRO --------------------------------------------------
ifeq ($(SIM),questa)
SIM_COMPILE = vlog -sv +incdir+tb -L uvm $(SV_SOURCES)
SIM_RUN     = vsim -c -do "run -all; quit -f" +UVM_TESTNAME=$(UVM_TESTNAME) +VECTOR_PATH=$(VECTOR) -L uvm $(TOP)
endif
ifeq ($(SIM),riviera)
SIM_COMPILE = vlog -sv +incdir+tb -l uvm $(SV_SOURCES)
SIM_RUN     = vsim -c -do "run -all; exit -f" +UVM_TESTNAME=$(UVM_TESTNAME) +VECTOR_PATH=$(VECTOR) $(TOP)
endif

# --- Synopsys VCS ----------------------------------------------------------
ifeq ($(SIM),vcs)
SIM_COMPILE = vcs -full64 -sverilog -ntb_opts uvm-1.2 +incdir+tb $(SV_SOURCES) -o $(WORK)/simv
SIM_RUN     = $(WORK)/simv +UVM_TESTNAME=$(UVM_TESTNAME) +VECTOR_PATH=$(VECTOR)
endif

# --- Cadence Xcelium -------------------------------------------------------
ifeq ($(SIM),xcelium)
SIM_COMPILE = xrun -sv -uvm -uvmhome CDNS-1.2 +incdir+tb $(SV_SOURCES) -elaborate -snapshot $(TOP)
SIM_RUN     = xrun -R -snapshot $(TOP) +UVM_TESTNAME=$(UVM_TESTNAME) +VECTOR_PATH=$(VECTOR)
endif

compile: regen
	mkdir -p $(WORK)
	$(SIM_COMPILE)

sim-golden: VECTOR := vectors/sem_chart_bound.jsonl
sim-golden: compile
	$(SIM_RUN)

sim-violation: VECTOR := vectors/sem_chart_violation.jsonl
sim-violation: compile
	$(SIM_RUN)

clean:
	rm -rf $(WORK)
