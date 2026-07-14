// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

//======================================================================
// chip_core -- 4x ROM-less CORDIC engine (SPI slave)
//
// Target slot: 0.5x0.5 (Quarter)
//   NUM_INPUT_PADS  = 6
//   NUM_BIDIR_PADS  = 38
//   NUM_ANALOG_PADS = 4
//
// Every core gets its own SPI pins. Only clk and rst_n are shared.
//
// PAD MAP (5 pads per core, contiguous):
//
//   Core 0 : bidir[ 0]=SCLK0 bidir[ 1]=MOSI0 bidir[ 2]=CSn0 bidir[ 3]=MISO0 bidir[ 4]=RDY0
//   Core 1 : bidir[ 5]=SCLK1 bidir[ 6]=MOSI1 bidir[ 7]=CSn1 bidir[ 8]=MISO1 bidir[ 9]=RDY1
//   Core 2 : bidir[10]=SCLK2 bidir[11]=MOSI2 bidir[12]=CSn2 bidir[13]=MISO2 bidir[14]=RDY2
//   Core 3 : bidir[15]=SCLK3 bidir[16]=MOSI3 bidir[17]=CSn3 bidir[18]=MISO3 bidir[19]=RDY3
//
//   bidir[37:20] = unused (driven low)
//   input[5:0]   = unused
//   analog[3:0]  = unused
//======================================================================

module chip_core #(
    parameter NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS
    )(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif

    input  wire clk,       // clock
    input  wire rst_n,     // reset (active low)

    input  wire [NUM_INPUT_PADS-1:0] input_in,   // Input value
    output wire [NUM_INPUT_PADS-1:0] input_pu,   // Pull-up
    output wire [NUM_INPUT_PADS-1:0] input_pd,   // Pull-down

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,   // Input value
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,  // Output value
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,   // Output enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,   // Input type (0=CMOS Buffer, 1=Schmitt Trigger)
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,   // Slew rate (0=fast, 1=slow)
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,   // Input enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,   // Pull-up
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,   // Pull-down

    inout  wire [NUM_ANALOG_PADS-1:0] analog     // Analog
);

    localparam NUM_CORES         = 4;
    localparam PADS_PER_CORE     = 5;   // SCLK, MOSI, CSn, MISO, RDY
    localparam PADS_USED         = NUM_CORES * PADS_PER_CORE;   // 20

    localparam DATA_WIDTH_CORDIC = 16;
    localparam DATA_WIDTH_SPI    = 8;
    localparam N_PE              = 13;

    // Per-core SPI nets
    wire [NUM_CORES-1:0] sclk;
    wire [NUM_CORES-1:0] mosi;
    wire [NUM_CORES-1:0] cs_n;
    wire [NUM_CORES-1:0] miso;
    wire [NUM_CORES-1:0] data_ready;

    // Input-only pads: unused
    assign input_pu = '0;
    assign input_pd = '0;

    // Bidir pad options are the same for every pad
    assign bidir_cs = '0;   // CMOS buffer
    assign bidir_sl = '0;   // fast slew
    assign bidir_pu = '0;   // no pull-up
    assign bidir_pd = '0;   // no pull-down
    assign bidir_ie = ~bidir_oe;

    // ------------------------------------------------------------------
    // Four CORDIC cores, each with its own SPI pins
    // ------------------------------------------------------------------
    genvar i;
    generate
        for (i = 0; i < NUM_CORES; i = i + 1) begin : g_core

            localparam B = i * PADS_PER_CORE;

            // Inputs: SCLK, MOSI, CSn
            assign sclk[i] = bidir_in[B+0];
            assign mosi[i] = bidir_in[B+1];
            assign cs_n[i] = bidir_in[B+2];

            assign bidir_oe [B+0] = 1'b0;
            assign bidir_oe [B+1] = 1'b0;
            assign bidir_oe [B+2] = 1'b0;
            assign bidir_out[B+0] = 1'b0;
            assign bidir_out[B+1] = 1'b0;
            assign bidir_out[B+2] = 1'b0;

            // Outputs: MISO, DATA_READY
            assign bidir_oe [B+3] = 1'b1;
            assign bidir_oe [B+4] = 1'b1;
            assign bidir_out[B+3] = miso[i];
            assign bidir_out[B+4] = data_ready[i];

            cordic_fsm #(
                .DATA_WIDTH_CORDIC (DATA_WIDTH_CORDIC),
                .DATA_WIDTH_SPI    (DATA_WIDTH_SPI),
                .N_PE              (N_PE)
            ) cordic_inst (
                .i_clk      (clk),
                .rst_n      (rst_n),
                .sclk       (sclk[i]),
                .mosi       (mosi[i]),
                .miso       (miso[i]),
                .cs_n       (cs_n[i]),
                .data_ready (data_ready[i])
            );

        end
    endgenerate

    // Unused bidir pads: drive low
    assign bidir_oe [NUM_BIDIR_PADS-1:PADS_USED] = '1;
    assign bidir_out[NUM_BIDIR_PADS-1:PADS_USED] = '0;

    // Tie off what we do not read
    logic _unused;
    assign _unused = &{input_in, analog, bidir_in};

endmodule

`default_nettype wire