module rst_sync (
    input  logic clk,
    input  logic rst_n_in,    // raw, asynchronous (from pad)
    output logic rst_n_out    // async assert, synchronous release
);
    logic ff1;
    always_ff @(posedge clk or negedge rst_n_in) begin
        if (!rst_n_in) begin
            ff1       <= 1'b0;
            rst_n_out <= 1'b0;
        end else begin
            ff1       <= 1'b1;
            rst_n_out <= ff1;
        end
    end
endmodule
