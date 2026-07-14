// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

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

    inout  wire [NUM_ANALOG_PADS-1:0] analog  // Analog
);

    // See here for usage: https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/IO/gf180mcu_fd_io/digital.html
    
    // Disable pull-up and pull-down for input
    assign input_pu = '0;
    assign input_pd = '0;

    // Set the bidir as output
    assign bidir_oe = '1;
    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_ie = ~bidir_oe;
    assign bidir_pu = '0;
    assign bidir_pd = '0;
    
    logic _unused;
    assign _unused = &{bidir_in, input_in[NUM_INPUT_PADS-1:3], analog};;



    // assigning the ports to the dedicated input pads
    assign sclk = input_in[0];
    assign mosi = input_in[1];
    assign cs_n = input_in[2];

    // assign the output pads
    assign bidir_out[0] = miso;
    assign bidir_out[1] = data_ready;
    assign bidir_out[NUM_BIDIR_PADS-1:2] = '0;

    // ------------------------------------------------------------------
    // ROM-less CORDIC engine (SPI slave)
    // ------------------------------------------------------------------

    localparam DATA_WIDTH_CORDIC = 16;
    localparam N_PE = 13;
    localparam DATA_WIDTH_SPI = 8;

    // internal wires to interface with cordic
    wire   sclk;
    wire   mosi;
    wire   miso;
    wire   cs_n;
    wire   data_ready;


    cordic_fsm # (.DATA_WIDTH_CORDIC(DATA_WIDTH_CORDIC),
                  .DATA_WIDTH_SPI(DATA_WIDTH_SPI),
                  .N_PE(N_PE)
    ) top_cordic_inst (
       .i_clk(clk),
       .rst_n(rst_n),
       .sclk(sclk),
       .mosi(mosi),
       .miso(miso),
       .cs_n(cs_n),
       .data_ready(data_ready)
    );



endmodule

`default_nettype wire
