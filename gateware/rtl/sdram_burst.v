// Burst-8 word SDRAM controller for the Tang Nano 20K's embedded 64 Mbit
// SDRAM (2K rows x 256 columns x 4 banks x 32 bit).
//
// Derived from nand2mario's byte controller (github.com/nand2mario/sdram-tang-nano-20k,
// via Seyviour/sdram-tang-nano-20k-os-example for the open toolchain): same
// init sequence, timing parameters and DQ sampling point, which are proven on
// hardware at 64.8 MHz. Changed to 32-bit words, burst length 8 (one request
// moves 8 consecutive words of a row) and internal refresh.
//
// Request: hold req_valid with req_write and req_addr (word address, low 3 bits
// ignored) until req_ready. Writes: wdata is taken on each wdata_take pulse
// (8 pulses, first one together with the request acceptance cycle + T_RCD).
// Reads: 8 rdata_valid pulses.
//
// RD_SAMPLE: cycle (counted from ACTIVATE = 0) at whose end word 0 is sampled.
// nand2mario samples at T_RCD+CAS+1; keep that unless hardware tests show a
// shifted read (then adjust by +-1).
`default_nettype none

module sdram_burst #(
    parameter         FREQ = 64_800_000,
    parameter [3:0]   CAS  = 4'd2,
    parameter [3:0]   T_WR = 4'd2,
    parameter [3:0]   T_MRD= 4'd2,
    parameter [3:0]   T_RP = 4'd1,
    parameter [3:0]   T_RCD= 4'd1,
    parameter [3:0]   T_RC = 4'd4,
    parameter [4:0]   RD_SAMPLE = 5'd4,       // = T_RCD + CAS + 1
    parameter         REFRESH_EVERY = 480     // cycles (~7.4 us at 64.8 MHz; spec: 4096 per 64 ms)
) (
    inout  wire [31:0] SDRAM_DQ,
    output reg  [10:0] SDRAM_A,
    output reg  [1:0]  SDRAM_BA,
    output wire        SDRAM_nCS,
    output reg         SDRAM_nWE,
    output reg         SDRAM_nRAS,
    output reg         SDRAM_nCAS,
    output wire        SDRAM_CLK,
    output wire        SDRAM_CKE,
    output reg  [3:0]  SDRAM_DQM,

    input  wire        clk,
    input  wire        clk_sdram,             // clk shifted 180 degrees
    input  wire        resetn,

    input  wire        req_valid,
    input  wire        req_write,
    input  wire [20:0] req_addr,              // {bank[1:0], row[10:0], col[7:0]} word address
    output wire        req_ready,
    input  wire [31:0] wdata,
    output reg         wdata_take,
    output reg  [31:0] rdata,
    output reg         rdata_valid,
    output reg         init_done
);
    reg        dq_oen;
    reg [31:0] dq_out;
    assign SDRAM_DQ  = dq_oen ? 32'bz : dq_out;
    assign SDRAM_CLK = clk_sdram;
    assign SDRAM_CKE = 1'b1;
    assign SDRAM_nCS = 1'b0;

    localparam INIT = 3'd0, CONFIG = 3'd1, IDLE = 3'd2, READ = 3'd3, WRITE = 3'd4, REFRESH = 3'd5;
    localparam CMD_SetModeReg = 3'b000, CMD_AutoRefresh = 3'b001, CMD_PreCharge = 3'b010,
               CMD_BankActivate = 3'b011, CMD_Write = 3'b100, CMD_Read = 3'b101, CMD_NOP = 3'b111;
    localparam [2:0]  BURST_LEN = 3'b011;     // 8
    localparam [10:0] MODE_REG = {4'b0, CAS[2:0], 1'b0, BURST_LEN};

    reg [2:0]  state;
    reg [4:0]  cycle;
    reg [20:0] addr_buf;
    reg        refresh_due;
    reg [11:0] refresh_cnt;
    reg        cfg_now;

    assign req_ready = (state == IDLE) && !refresh_due;

    always @(posedge clk) begin
        cycle <= (cycle == 5'd31) ? cycle : cycle + 5'd1;
        {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_NOP;
        wdata_take  <= 1'b0;
        rdata_valid <= 1'b0;

        // refresh timer
        if (refresh_cnt == REFRESH_EVERY - 1) begin refresh_cnt <= 0; refresh_due <= 1'b1; end
        else refresh_cnt <= refresh_cnt + 1'b1;

        case (state)
        INIT: if (cfg_now) begin state <= CONFIG; cycle <= 0; end

        CONFIG: begin
            if (cycle == 0) begin
                {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_PreCharge; SDRAM_A[10] <= 1'b1;
            end else if (cycle == T_RP || cycle == T_RP + T_RC) begin
                {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_AutoRefresh;
            end else if (cycle == T_RP + 2 * T_RC) begin
                {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_SetModeReg; SDRAM_A <= MODE_REG; SDRAM_BA <= 2'b00;
            end else if (cycle == T_RP + 2 * T_RC + T_MRD) begin
                state <= IDLE; init_done <= 1'b1;
            end
        end

        IDLE: begin
            if (refresh_due) begin
                {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_AutoRefresh;
                refresh_due <= 1'b0;
                state <= REFRESH; cycle <= 5'd1;
            end else if (req_valid) begin
                {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_BankActivate;
                SDRAM_BA <= req_addr[20:19];
                SDRAM_A  <= req_addr[18:8];
                addr_buf <= req_addr;
                state <= req_write ? WRITE : READ;
                cycle <= 5'd1;
                if (req_write) wdata_take <= 1'b1;     // word 0 is latched next cycle
            end
        end

        // write: cycle T_RCD issues WRITE with word 0, words 1..7 follow on consecutive cycles
        WRITE: begin
            if (cycle < T_RCD + 7) wdata_take <= 1'b1;
            if (cycle == T_RCD) begin
                {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_Write;
                SDRAM_A[10] <= 1'b1;                                   // auto precharge
                SDRAM_A[9:0] <= {2'b00, addr_buf[7:3], 3'b000};
                SDRAM_DQM <= 4'b0000;
            end
            if (cycle >= T_RCD && cycle < T_RCD + 8) begin
                dq_out <= wdata;
                dq_oen <= 1'b0;
            end else if (cycle == T_RCD + 8) begin
                dq_oen <= 1'b1;
            end
            if (cycle == T_RCD + 8 + T_WR + T_RP) state <= IDLE;
        end

        READ: begin
            if (cycle == T_RCD) begin
                {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_Read;
                SDRAM_A[10] <= 1'b1;
                SDRAM_A[9:0] <= {2'b00, addr_buf[7:3], 3'b000};
                SDRAM_DQM <= 4'b0000;
            end
            if (cycle >= RD_SAMPLE && cycle < RD_SAMPLE + 8) begin
                rdata <= SDRAM_DQ;
                rdata_valid <= 1'b1;
            end
            if (cycle == RD_SAMPLE + 8 + T_RP) state <= IDLE;
        end

        REFRESH: if (cycle == T_RC) state <= IDLE;
        default: state <= INIT;
        endcase

        if (!resetn) begin
            dq_oen <= 1'b1; SDRAM_DQM <= 4'b0000; state <= INIT; init_done <= 1'b0;
            refresh_due <= 1'b0; refresh_cnt <= 0;
        end
    end

    // 200 us power-up wait, then configure
    reg [15:0] rst_cnt;
    reg rst_done, rst_done_p1;
    always @(posedge clk) begin
        rst_done_p1 <= rst_done;
        cfg_now <= rst_done & ~rst_done_p1;
        if (rst_cnt != FREQ / 1000 * 200 / 1000) begin rst_cnt <= rst_cnt + 1'b1; rst_done <= 1'b0; end
        else rst_done <= 1'b1;
        if (!resetn) begin rst_cnt <= 0; rst_done <= 1'b0; end
    end
endmodule
`default_nettype wire
