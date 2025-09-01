TARGET = cordic
TOP = cordic_fsm

OBJS += ../../src/top_fsm.v ../../src/top_CORDIC_ENGINE_v1.v ../../src/spi_slave.v ../../src/dynamic_atan.v ../../src/CORDIC_Engine_v1.v  

all: ${TARGET}.bit

$(TARGET).ys: $(OBJS)
	yosys -p "synth_ecp5 -top ${TOP} -json $@" $(OBJS) > yosys.log
	@grep Warn yosys.log || true
	@grep Error yosys.log || true
	@grep "   Number of cells" yosys.log
	@grep "     TRELLIS_FF" yosys.log | awk '{sum+=$$2;}END{printf("     TRELLIS_FF* %21d\n", sum);}'
	@grep "     LUT" yosys.log
	@echo

$(TARGET)_out.config: $(TARGET).ys
	nextpnr-ecp5 --85k --package CABGA381 --speed 6 --json $< --textcfg $@ --lpf ulx3s_85f.lpf > nextpnr.log 2>& 1
	@grep Warn nextpnr.log || true
	@grep Error nextpnr.log || true
	@grep "Max frequency.*clk" nextpnr.log | tail -1
	@echo

$(TARGET).bit: $(TARGET)_out.config
	ecppack --svf ${TARGET}.svf $< $@

${TARGET}.svf: ${TARGET}.bit

prog: ${TARGET}.bit
	 fujprog ${TARGET}.bit

clean:
	rm -f *.svf *.bit *.config *.ys *.log

.PHONY: all prog clean