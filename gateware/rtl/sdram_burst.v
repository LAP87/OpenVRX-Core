// Burst-8 word SDRAM controller for the Tang Nano 20K's embedded 64 Mbit
// SDRAM (2K rows x 256 columns x 4 banks x 32 bit).
//
// Derived from nand2mario's byte controller (github.com/nand2mario/sdram-tang-nano-20k,
// via Seyviour/sdram-tang-nano-20k-os-example for the open toolchain): the state
// machine, the init sequence and the rule "sample read data CAS+1 clocks after
// the READ command". Changed here: 32-bit words, burst length 8 (one request
// moves 8 consecutive words of a row), internal refresh, and T_RCD/T_RP/T_RC
// of 2/2/6 clocks instead of 1/1/4.
//
// What is proven on hardware and what is not (upstream sources read 2026-10-05):
//  * nand2mario's example runs at 27 MHz. NESTang (src/sdram_nes.v) runs this
//    SDRAM at 64.8 MHz. Both give the SDRAM a clock shifted 225 degrees, read
//    single words (burst length 1) and sample them CAS+1 clocks after READ.
//  * This controller has not run on hardware, and its 8-word bursts are not
//    covered by upstream. In a burst each word leaves the bus tOH (2.5 ns)
//    after the next SDRAM clock edge and the following one is valid tAC (6 ns)
//    after it; a single word stays on the released bus. So here the sample
//    point must hit a window of one clock period less 3.5 ns, and where that
//    window lies depends on the board's clock and data delays, which nobody
//    has measured.
//  * 2/2/6 are the values NESTang declares (its start-up sequence uses T_RP
//    and T_RC; its accesses issue READ one or two clocks after ACTIVATE,
//    depending on the port). The EM638325-6 datasheet figures that
//    sim/sdram_model.v checks (tRCD and tRP 18 ns, tRC 60 ns) need 2/2/4 at
//    64.8 MHz; 1/1 are 15.4 ns and do not meet them.
//
// Request: hold req_valid with req_write and req_addr (word address, low 3 bits
// ignored) until req_ready. Writes: wdata is taken at the end of each cycle in
// which wdata_take is high (8 cycles, starting T_RCD cycles after the request
// was accepted). Reads: 8 rdata_valid pulses.
//
// RD_SAMPLE: cycle (counted from ACTIVATE = 0) at whose end word 0 is sampled.
// The default is CAS+1 clocks after READ, as upstream. With the 225-degree
// clock that is 0.375 period (5.8 ns) after the SDRAM clock edge at which the
// word is valid. The word is at the controller's flip-flops then if the
// delay of the clock to the SDRAM plus that of the data back is between 3.3
// and 15.2 ns (sim/test_sdram.py checks both limits). Outside that window
// the read is shifted by a word or broken: change RD_SAMPLE or the phase.
`default_nettype none

module sdram_burst #(
    parameter         FREQ = 64_800_000,
    parameter [3:0]   CAS  = 4'd2,
    parameter [3:0]   T_WR = 4'd2,            // clocks: write recovery
    parameter [3:0]   T_MRD= 4'd2,            // clocks: mode register set to the next command
    parameter [3:0]   T_RP = 4'd2,            // clocks (15.43 ns each): precharge to the next command
    parameter [3:0]   T_RCD= 4'd2,            // clocks: ACTIVATE to READ/WRITE
    parameter [3:0]   T_RC = 4'd6,            // clocks: refresh to the next command
    parameter [4:0]   RD_SAMPLE = 5'd5,       // = T_RCD + CAS + 1
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
    input  wire        clk_sdram,             // clk shifted 225 degrees (clocks_sdram.v)
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
                if (req_write && T_RCD == 4'd1) wdata_take <= 1'b1;    // word 0 is latched next cycle
            end
        end

        // write: cycle T_RCD issues WRITE with word 0, words 1..7 follow on consecutive cycles.
        // wdata_take is high during cycles T_RCD .. T_RCD+7.
        WRITE: begin
            if (cycle + 5'd1 >= T_RCD && cycle < T_RCD + 7) wdata_take <= 1'b1;
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
