// Behavioural SDR SDRAM model for simulation only: x32, 4 banks, CAS latency and
// burst length from the mode register, auto-precharge assumed (no row checks
// beyond "a row must be open"). Clocked by the SDRAM clock (controller clock
// inverted), like the real wiring. Depth is limited by AW (address is wrapped).
`default_nettype none
module sdram_model #(
    parameter AW = 16                // simulated words = 2^AW
) (
    input  wire        clk,
    input  wire        cke,
    input  wire        ncs, nras, ncas, nwe,
    input  wire [1:0]  ba,
    input  wire [10:0] a,
    input  wire [3:0]  dqm,
    inout  wire [31:0] dq
);
    reg [31:0] mem [0:(1<<AW)-1];
    // testbench peek port (cocotb cannot index large Icarus memories directly)
    reg  [AW-1:0] peek_addr = 0;
    wire [31:0]   peek_data = mem[peek_addr];
    reg [10:0] open_row [0:3];
    reg [2:0]  cas_lat = 3'd2;
    reg [3:0]  burst_len = 4'd1;

    // read pipeline: data to drive at future edges
    reg [31:0] rd_data [0:15];
    reg        rd_en   [0:15];
    reg [31:0] dq_drive;
    reg        dq_oe;
    assign dq = dq_oe ? dq_drive : 32'bz;

    integer wr_left, wr_addr, i;
    integer errors;            // protocol errors seen (checked by the testbench)
    integer refreshes;
    initial begin
        wr_left = 0; errors = 0; refreshes = 0; dq_oe = 0;
        for (i = 0; i < 16; i = i + 1) rd_en[i] = 0;
        for (i = 0; i < 4; i = i + 1) open_row[i] = 11'h7FF;
    end

    function integer waddr(input [1:0] b, input [10:0] row, input [7:0] col);
        waddr = {b, row, col} & ((1 << AW) - 1);
    endfunction

    always @(posedge clk) begin
        // shift the read pipeline and drive this edge's word
        dq_oe    <= rd_en[0];
        dq_drive <= rd_data[0];
        for (i = 0; i < 15; i = i + 1) begin rd_en[i] = rd_en[i+1]; rd_data[i] = rd_data[i+1]; end
        rd_en[15] = 0;

        // continuing write burst
        if (wr_left > 0) begin
            mem[wr_addr] <= dq;
            wr_addr = (wr_addr & ~7) | ((wr_addr + 1) & 7);
            wr_left = wr_left - 1;
        end

        if (cke && !ncs) case ({nras, ncas, nwe})
            3'b000: begin                                   // load mode register
                cas_lat   <= a[6:4];
                burst_len <= (a[2:0] == 3'b011) ? 4'd8 : (a[2:0] == 3'b010) ? 4'd4 :
                             (a[2:0] == 3'b001) ? 4'd2 : 4'd1;
            end
            3'b001: refreshes = refreshes + 1;               // auto refresh
            3'b011: open_row[ba] <= a;                       // activate
            3'b010: ;                                        // precharge
            3'b100: begin                                    // write (data on DQ this edge)
                if (open_row[ba] == 11'h7FF) errors = errors + 1;
                wr_addr = waddr(ba, open_row[ba], a[7:0]);
                mem[wr_addr] <= dq;
                wr_addr = (wr_addr & ~7) | ((wr_addr + 1) & 7);
                wr_left = burst_len - 1;
                if (a[10]) open_row[ba] <= 11'h7FF;          // auto precharge (after burst)
            end
            3'b101: begin                                    // read: words appear CAS edges later
                if (open_row[ba] == 11'h7FF) errors = errors + 1;
                for (i = 0; i < burst_len; i = i + 1) begin
                    rd_en[cas_lat - 1 + i]   = 1;
                    rd_data[cas_lat - 1 + i] = mem[waddr(ba, open_row[ba], (a[7:0] & ~7) | ((a[7:0] + i) & 7))];
                end
                if (a[10]) open_row[ba] <= 11'h7FF;
            end
            default: ;
        endcase
    end
endmodule
`default_nettype wire
