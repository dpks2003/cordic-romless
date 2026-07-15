module cordic_fsm #(
    parameter DATA_WIDTH_CORDIC = 16,
    parameter DATA_WIDTH_SPI = 8,
    parameter N_PE = 13
)(
    input  wire                    i_clk,
    input  wire                    rst_n,
    input  wire                    sclk,
    input  wire                    mosi,
    output wire                    miso,
    input  wire                    cs_n,
    output reg                     data_ready 
);

    // SPI interface
    reg  [DATA_WIDTH_SPI-1:0] spi_tx_data;
    wire [DATA_WIDTH_SPI-1:0] spi_rx_data;     
    wire spi_rx_valid;
    wire spi_tx_req;

    SPI_Slave #(
        .DATA_WIDTH(DATA_WIDTH_SPI)
    ) spi_slave_inst (
        .clk(i_clk),
        .rst_n(rst_n),
        .sclk(sclk),
        .mosi(mosi),
        .miso(miso),
        .cs_n(cs_n),
        .tx_data(spi_tx_data),
        .rx_data(spi_rx_data),
        .tx_req(spi_tx_req),
        .rx_valid(spi_rx_valid)
    );

    // CORDIC
    wire [DATA_WIDTH_CORDIC-1:0] in_x, in_y, in_alpha, in_atan_0;
    wire [DATA_WIDTH_CORDIC-1:0] out_costheta, out_sintheta, out_alpha;
    wire o_valid_out;
    reg valid_cordic_angle;

    top_CORDIC_Engine_v1 #(
        .DATA_WIDTH(DATA_WIDTH_CORDIC),
        .N_PE(N_PE)
    ) cordic_inst (
        .i_clk(i_clk),
        .i_rst_n(rst_n),
        .in_x(in_x),
        .in_y(in_y),
        .in_alpha(in_alpha),
        .in_atan_0(in_atan_0),
        .i_valid_in(valid_cordic_angle),
        .out_costheta(out_costheta),
        .out_sintheta(out_sintheta),
        .out_alpha(out_alpha),
        .o_valid_out(o_valid_out)
    );

    // FSM States
    localparam [2:0] S_IDLE       = 3'd0,
                     S_RX         = 3'd1,
                     S_WAIT       = 3'd2,
                     S_LOAD       = 3'd3,
                     S_TX         = 3'd4,
                     S_DONE       = 3'd5;

    reg [2:0] state;
    reg [3:0] rx_byte_count;
    reg [2:0] tx_byte_count;
    reg [63:0] r_spi_rx_data;
    reg [47:0] r_spi_tx_data;


    assign in_x      = r_spi_rx_data[15:0];
    assign in_y      = r_spi_rx_data[31:16];
    assign in_alpha  = r_spi_rx_data[47:32];
    assign in_atan_0 = r_spi_rx_data[63:48];

    always @(posedge i_clk ) begin
        if (!rst_n) begin
            state              <= S_IDLE;
            rx_byte_count      <= 0;
            tx_byte_count      <= 0;
            r_spi_rx_data      <= 0;
            r_spi_tx_data      <= 0;
            valid_cordic_angle <= 0;
            spi_tx_data        <= 0;
            data_ready         <= 0;
        end else begin
            case (state)
                S_IDLE: begin
                    valid_cordic_angle <= 0;
                    tx_byte_count      <= 0;
                    rx_byte_count      <= 0;
                    data_ready         <= 0;
                    if (spi_rx_valid) begin
                        r_spi_rx_data[7:0] <= spi_rx_data;
                        rx_byte_count <= 1;
                        state <= S_RX;
                    end
                end

                S_RX: begin
                    valid_cordic_angle <= 0;
                    if (spi_rx_valid) begin
                        r_spi_rx_data[((rx_byte_count+1)*8)-1 -: 8] <= spi_rx_data;
                        rx_byte_count <= rx_byte_count + 1;
                        if (rx_byte_count == 7) begin
                            valid_cordic_angle <= 1;
                            state <= S_WAIT;
                        end
                    end
                end

                S_WAIT: begin
                    valid_cordic_angle <= 0;
                    if (o_valid_out) begin
                        r_spi_tx_data <= {out_alpha, out_costheta, out_sintheta}; // 56 bits
                        state <= S_LOAD;
                        data_ready <= 1'b1;
                    end
                end

                S_LOAD: begin
                    spi_tx_data   <= r_spi_tx_data[7:0];
                    tx_byte_count <= 1; 
                    state <= S_TX;
                end

                S_TX: begin
                    if (spi_tx_req) begin
                        spi_tx_data   <= r_spi_tx_data[15:8];
                        r_spi_tx_data <= r_spi_tx_data >> 8;
                        tx_byte_count <= tx_byte_count + 1;
                        if (tx_byte_count == 6) begin
                            state <= S_DONE;
                    end
                    end
                end

                S_DONE: begin
                    if (cs_n) begin
                        state <= S_IDLE;
                        data_ready <= 1'b0;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
