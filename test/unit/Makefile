# Module-level tests. Each block is simulated alone against its own test module.
#
#   make              run every module
#   make fir_mac      run one module

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(abspath $(CURDIR)/../../src)
MODEL_DIR = $(abspath $(CURDIR)/../../model)

MODULES = fir_mac output_stage sample_history coef_regs strobe_sync fir_controller spi_interface

SOURCES_fir_mac = fir_mac.v
SOURCES_output_stage = output_stage.v
SOURCES_sample_history = sample_history.v
SOURCES_coef_regs = coef_regs.v
SOURCES_strobe_sync = strobe_sync.v sync_2ff.v
SOURCES_fir_controller = fir_controller.v
SOURCES_spi_interface = spi_interface.v sync_2ff.v

.PHONY: all clean $(MODULES)

all: $(MODULES)

$(MODULES):
	rm -f results_$@.xml
	$(MAKE) -f $(lastword $(MAKEFILE_LIST)) sim-one MODULE_NAME=$@

clean::
	rm -rf sim_build results_*.xml __pycache__

ifdef MODULE_NAME
export PYTHONPATH := $(MODEL_DIR):$(PYTHONPATH)
VERILOG_SOURCES = $(addprefix $(SRC_DIR)/,$(SOURCES_$(MODULE_NAME)))
TOPLEVEL = $(MODULE_NAME)
COCOTB_TEST_MODULES = test_$(MODULE_NAME)
SIM_BUILD = sim_build/$(MODULE_NAME)
COCOTB_RESULTS_FILE = results_$(MODULE_NAME).xml

sim-one: $(COCOTB_RESULTS_FILE)

include $(shell cocotb-config --makefiles)/Makefile.sim
endif
