/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_cordic_16 (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // All output pins must be assigned. If not used, assign to 0.
  assign uio_out = 0;
  assign uio_oe  = 0;

  // List all unused inputs to prevent warnings
  wire _unused ;
  assign _unused = &{ena,uio_in,ui_in[7:3], 1'b0};


    localparam DATA_WIDTH_CORDIC = 16;
    localparam N_PE = 13;
    localparam DATA_WIDTH_SPI = 8;
    
    // internal wires to interface with cordic 
    wire   sclk;
    wire   mosi;
    wire   miso;
    wire   cs_n;
    wire   data_ready;


   // assiging the ports to the dedicated io's
    assign sclk = ui_in[0];
    assign mosi = ui_in[1];
    assign cs_n = ui_in[2];

    // assign the output port 

    assign uo_out[0] = miso;
    assign uo_out[1] = data_ready;
    assign uo_out[7:2] = 6'b0;
    
   /*------------- 16 bit cordic instantiatyion------------------ */
    
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
