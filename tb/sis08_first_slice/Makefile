TOPLEVEL_LANG ?= verilog
SIM ?= icarus

SOS_ROOT := $(abspath ../..)

VERILOG_SOURCES := \
	$(SOS_ROOT)/rtl/sos_fifo_sync/sos_fifo_sync.sv \
	$(SOS_ROOT)/rtl/sos_arbiter_priority/sos_arbiter_priority.sv \
	$(SOS_ROOT)/rtl/sos_mailbox/sos_mailbox.sv \
	$(SOS_ROOT)/rtl/sos_credit_counter/sos_credit_counter.sv \
	$(SOS_ROOT)/tb/sis08_first_slice/sis08_first_slice_top.sv

TOPLEVEL := sis08_first_slice_top
MODULE := test_sis08_first_slice

include $(shell cocotb-config --makefiles)/Makefile.sim
