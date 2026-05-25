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
#   make sim-golden-uvm2     — UVM 2.0 (IEEE 1800.2-2017) variant of sim-golden.
#   make sim-violation-uvm2  — UVM 2.0 (IEEE 1800.2-2017) variant of sim-violation.
#   make clean          — remove the work directory.
#
# Simulator selection: `make SIM=questa sim-golden` or override with
# the per-tool target. Default SIM=questa.
#
# UVM version selection: the SIM_* recipes below parameterise the UVM
# library against `UVM_VERSION`. Defaults:
#
#     UVM_VERSION ?= 1.2          — primary target per INV-S-HDL-F-5.
#     UVM_HOME    (per-SIM)       — auto-resolved against the simulator
#                                    vendor's UVM install convention; can
#                                    be overridden on the command line.
#
# The `sim-golden-uvm2` / `sim-violation-uvm2` targets override
# `UVM_VERSION=2.0` for a single invocation. The UVM-1.2 targets
# `sim-golden` / `sim-violation` remain byte-identical to their
# pre-carry-forward form (regression guard: don't flip the default).
#
# Notes:
#   * The Makefile is a *recipe template* — most enterprise UVM shops
#     already have site-specific simulator wrappers; the rules below
#     show the canonical command-line shape per vendor.
#   * No simulator is bundled. Acceptance gate (e) is satisfied by the
#     artifact set being able to elaborate + run on any UVM 1.2-capable
#     simulator; vendor binaries are customer-owned.
#   * UVM 2.0 cross-runtime smoke is exercised by the
#     `.github/workflows/sos-uvm-smoke.yml` CI job (parse-only — no
#     vendor simulator invocation in CI; see §15 wave-2-c entry in
#     `docs/concepts/SOS-08-F-CONCEPTS.md`).

REPO_ROOT       := $(abspath $(CURDIR)/../..)
CHART           := $(REPO_ROOT)/rtos_kernel.scxml
CODEGEN         := $(REPO_ROOT)/tools/sos-codegen/main.py
WORK            := work
SIM             ?= questa
UVM_TESTNAME    ?= sos_kernel_test
TOP             := sos_kernel_tb_top

# UVM version target. Default is 1.2 per INV-S-HDL-F-5 (UVM 1.2 grammar
# + UVM 2.0 forward-compatible). The `sim-*-uvm2` targets override.
UVM_VERSION     ?= 1.2

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

.PHONY: all regen compile sim-golden sim-violation sim-golden-uvm2 sim-violation-uvm2 clean help

all: help

help:
	@echo "SOS-08-F wave-2 acceptance gate (e) example flow"
	@echo "  make regen                       — regenerate tb/sos_uvm_seq_pkg.sv from chart"
	@echo "  make SIM=<sim> sim-golden        — run golden vector (UVM 1.2; expect pass)"
	@echo "  make SIM=<sim> sim-violation     — run violation vector (UVM 1.2; expect chart-vocab error)"
	@echo "  make SIM=<sim> sim-golden-uvm2   — run golden vector (UVM 2.0; expect pass)"
	@echo "  make SIM=<sim> sim-violation-uvm2 — run violation vector (UVM 2.0; expect chart-vocab error)"
	@echo "  make clean                       — remove $(WORK)/"
	@echo ""
	@echo "Supported SIM= values: questa, vcs, xcelium, riviera"
	@echo "Current UVM_VERSION=$(UVM_VERSION) (override via UVM_VERSION=2.0)"

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
# UVM_HOME default for Questa: vendor ships UVM under $MTI_HOME/verilog_src/uvm-<ver>.
UVM_HOME    ?= $(MTI_HOME)/verilog_src/uvm-$(UVM_VERSION)
SIM_COMPILE = vlog -sv +incdir+tb -L uvm-$(UVM_VERSION) $(SV_SOURCES)
SIM_RUN     = vsim -c -do "run -all; quit -f" +UVM_TESTNAME=$(UVM_TESTNAME) +VECTOR_PATH=$(VECTOR) -L uvm-$(UVM_VERSION) $(TOP)
endif
ifeq ($(SIM),riviera)
UVM_HOME    ?= $(ALDEC_PATH)/vlib/uvm-$(UVM_VERSION)
SIM_COMPILE = vlog -sv +incdir+tb -l uvm-$(UVM_VERSION) $(SV_SOURCES)
SIM_RUN     = vsim -c -do "run -all; exit -f" +UVM_TESTNAME=$(UVM_TESTNAME) +VECTOR_PATH=$(VECTOR) $(TOP)
endif

# --- Synopsys VCS ----------------------------------------------------------
ifeq ($(SIM),vcs)
# VCS -ntb_opts accepts uvm-1.2 or uvm-2.0 (IEEE 1800.2 builds).
UVM_HOME    ?= $(VCS_HOME)/etc/uvm-$(UVM_VERSION)
SIM_COMPILE = vcs -full64 -sverilog -ntb_opts uvm-$(UVM_VERSION) +incdir+tb $(SV_SOURCES) -o $(WORK)/simv
SIM_RUN     = $(WORK)/simv +UVM_TESTNAME=$(UVM_TESTNAME) +VECTOR_PATH=$(VECTOR)
endif

# --- Cadence Xcelium -------------------------------------------------------
ifeq ($(SIM),xcelium)
# xrun -uvmhome accepts CDNS-1.2 or CDNS-2.0 (IEEE 1800.2 builds).
ifeq ($(UVM_VERSION),1.2)
XRUN_UVMHOME := CDNS-1.2
else
XRUN_UVMHOME := CDNS-$(UVM_VERSION)
endif
UVM_HOME    ?= $(CDS_INST_DIR)/tools/methodology/UVM/$(XRUN_UVMHOME)
SIM_COMPILE = xrun -sv -uvm -uvmhome $(XRUN_UVMHOME) +incdir+tb $(SV_SOURCES) -elaborate -snapshot $(TOP)
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

# UVM 2.0 variants — override UVM_VERSION for the single invocation.
# Implemented as recursive make calls so the per-SIM ifeq blocks above
# re-evaluate with UVM_VERSION=2.0 (otherwise the -L / -ntb_opts /
# -uvmhome strings would still read 1.2).
sim-golden-uvm2:
	$(MAKE) UVM_VERSION=2.0 sim-golden

sim-violation-uvm2:
	$(MAKE) UVM_VERSION=2.0 sim-violation

clean:
	rm -rf $(WORK)
