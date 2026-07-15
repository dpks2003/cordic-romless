// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

//======================================================================
// chip_core -- NUM_CORES x ROM-less CORDIC engine (SPI slave)
//
// Target slot: 0.5x0.5 (Quarter)
//   NUM_INPUT_PADS  = 6
//   NUM_BIDIR_PADS  = 38
//   NUM_ANALOG_PADS = 4
//
// Every core gets its own SCLK, MOSI, CSn, MISO and RDY pin.
// Only clk and rst_n are shared. Nothing is bussed on-chip -- if you
// want one host to drive several cores, wire them together on the board.
//
//----------------------------------------------------------------------
// PAD MAP (grouped by signal, so a bussed SCLK/MOSI fans out to
//          adjacent pads instead of hopping around the ring)
//
//   NUM_CORES = 8:
//
//     input[0..5]    = CSn[0..3]      (first 6 chip selects)
//
//     bidir[ 0.. 7]  = SCLK[0..7]     (in)
//     bidir[ 8..15]  = MOSI[0..7]     (in)
//     bidir[16..17]  = CSn[4..7]      (in)  -- overflow, input pads full
//     bidir[18..25]  = MISO[0..7]     (out)
//     bidir[26..33]  = RDY[0..7]      (out)
//     bidir[34..37]  = unused, driven low
//
//   NUM_CORES = 6 fits perfectly: all 6 CSn on the input pads, no
//   overflow, and only 24 bidir pads used.
//
//   Max is 8: 24 inputs (6 on input pads, 18 on bidir) + 16 outputs
//   = 34 bidir. A 9th core needs 39 and does not fit.
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

    // ------------------------------------------------------------------
    // Configuration -- change NUM_CORES here, the pad map follows
    // ------------------------------------------------------------------
    localparam NUM_CORES         = 8;

    localparam DATA_WIDTH_CORDIC = 16;
    localparam DATA_WIDTH_SPI    = 8;
    localparam N_PE              = 13;

    // CSn goes on the input-only pads first, overflow onto bidir.
    localparam CS_ON_INPUT = (NUM_CORES < NUM_INPUT_PADS) ? NUM_CORES : NUM_INPUT_PADS;
    localparam CS_ON_BIDIR = NUM_CORES - CS_ON_INPUT;

    // Bidir pad map
    localparam SCLK_BASE = 0;
    localparam MOSI_BASE = SCLK_BASE + NUM_CORES;
    localparam CSN_BASE  = MOSI_BASE + NUM_CORES;
    localparam MISO_BASE = CSN_BASE  + CS_ON_BIDIR;
    localparam RDY_BASE  = MISO_BASE + NUM_CORES;
    localparam PADS_USED = RDY_BASE  + NUM_CORES;

    // ------------------------------------------------------------------
    // Per-core SPI nets
    // ------------------------------------------------------------------
    wire [NUM_CORES-1:0] sclk;
    wire [NUM_CORES-1:0] mosi;
    wire [NUM_CORES-1:0] cs_n;
    wire [NUM_CORES-1:0] miso;
    wire [NUM_CORES-1:0] data_ready;

    // ------------------------------------------------------------------
    // Pad options: same for every pad
    // ------------------------------------------------------------------
    assign input_pu = '0;
    assign input_pd = '0;

    assign bidir_cs = '0;   // CMOS buffer
    assign bidir_sl = '0;   // fast slew
    assign bidir_pu = '0;   // no pull-up
    assign bidir_pd = '0;   // no pull-down
    assign bidir_ie = ~bidir_oe;

    // ------------------------------------------------------------------
    // The cores
    // ------------------------------------------------------------------
    genvar i;
    generate
        for (i = 0; i < NUM_CORES; i = i + 1) begin : g_core

            // ---- SCLK, MOSI : bidir pads used as inputs ----
            assign sclk[i] = bidir_in[SCLK_BASE + i];
            assign mosi[i] = bidir_in[MOSI_BASE + i];

            assign bidir_oe [SCLK_BASE + i] = 1'b0;
            assign bidir_out[SCLK_BASE + i] = 1'b0;

            assign bidir_oe [MOSI_BASE + i] = 1'b0;
            assign bidir_out[MOSI_BASE + i] = 1'b0;

            // ---- CSn : input-only pad if there is one, else bidir ----
            if (i < CS_ON_INPUT) begin : g_cs_input
                assign cs_n[i] = input_in[i];
            end
            else begin : g_cs_bidir
                assign cs_n[i] = bidir_in[CSN_BASE + i - CS_ON_INPUT];

                assign bidir_oe [CSN_BASE + i - CS_ON_INPUT] = 1'b0;
                assign bidir_out[CSN_BASE + i - CS_ON_INPUT] = 1'b0;
            end

            // ---- MISO, RDY : bidir pads used as outputs ----
            assign bidir_oe [MISO_BASE + i] = 1'b1;
            assign bidir_out[MISO_BASE + i] = miso[i];

            assign bidir_oe [RDY_BASE + i]  = 1'b1;
            assign bidir_out[RDY_BASE + i]  = data_ready[i];

            // ---- The core ----
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

    // ------------------------------------------------------------------
    // Spare bidir pads: drive low
    // ------------------------------------------------------------------
    assign bidir_oe [NUM_BIDIR_PADS-1:PADS_USED] = '1;
    assign bidir_out[NUM_BIDIR_PADS-1:PADS_USED] = '0;

    // ------------------------------------------------------------------
    // Tie off what we do not read
    // ------------------------------------------------------------------
    logic _unused;
    assign _unused = &{input_in, analog, bidir_in};

endmodule

`default_nettype wire