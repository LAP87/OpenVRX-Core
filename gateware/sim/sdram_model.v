// Behavioural SDR SDRAM for simulation only: 2M x 32 in four banks (2048 rows x 256 columns), the
// organisation of the Tang Nano 20K's embedded SDRAM. Depth is limited by AW (the address wraps).
//
// The model has the timing of a real part, not of RTL:
//
//  * Read data. A READ registered at clock edge n with CAS latency CL has word 0 valid AT edge n+CL: it
//    becomes valid tAC after edge n+CL-1 and stays until tOH after edge n+CL. Then the next word of the
//    burst follows the same way, or the outputs turn off (by tHZ). Between tOH and tAC the outputs are
//    changing and the model drives X, so a controller that samples there reads X.
//  * Board delays (parameters, below): the clock reaches the SDRAM late, read data reach the controller's
//    flip-flop late, commands and write data reach the SDRAM late.
//  * Protocol checks, counted per rule and in `errors`: tRCD, tRP, tRC, tRFC, tRAS, tRRD, tWR, tMRD, the
//    200 us power-up pause and the initialisation sequence, the refresh interval, set-up and hold of
//    commands, addresses and write data against the SDRAM clock, clock period and high/low time, access
//    to a closed row, commands that are illegal in the bank's state, undefined write data, two drivers on
//    DQ. The negative controls are in test_sdram.py.
//
// Device timing: Gowin does not name the embedded die. DS226 (GW2AR data sheet), "SDR SDRAM" features,
// gives access time 5.4 ns, 166 MHz, CAS latency 2 or 3 and 4096 refresh cycles per 64 ms, which are
// the -6 grade figures of a 64 Mbit x32 SDR SDRAM. The values below are from the Etron EM638325
// datasheet, Rev. 3.2 (Aug. 2015), Table 16 "Electrical Characteristics and Recommended A.C. Operating
// Conditions", column -6, and its Note 11 (power-up sequence). That the embedded die behaves like this
// part is an ASSUMPTION.
//
// Not modelled: burst stop, bursts interrupted by another command (counted as an error), interleaved
// and full-page bursts, single-location write mode, clock suspend, power down and self refresh.
`timescale 1ps/1ps        // every time in this file is an integer number of picoseconds
`default_nettype none
module sdram_model #(
    parameter AW = 16,                   // simulated words = 2^AW
    // ---- Etron EM638325-6, Table 16 (ps) ----
    parameter T_AC2_PS   = 6000,         // tAC max, CAS latency 2
    parameter T_AC3_PS   = 5400,         // tAC max, CAS latency 3
    parameter T_OH_PS    = 2500,         // tOH min
    parameter T_LZ_PS    = 1000,         // tLZ min (tHZ max is listed for CAS latency 3 only and equals
                                         // tAC there; the model turns the outputs off at tAC)
    parameter T_IS_PS    = 1500,         // tIS min: data, address and control set-up
    parameter T_IH_PS    = 1000,         // tIH min: data, address and control hold
    parameter T_CK2_PS   = 10000,        // tCK min, CAS latency 2
    parameter T_CK3_PS   = 6000,         // tCK min, CAS latency 3
    parameter T_CH_PS    = 2500,         // tCH min
    parameter T_CL_PS    = 2500,         // tCL min
    parameter T_RCD_PS   = 18000,        // tRCD min: ACTIVATE to READ/WRITE
    parameter T_RP_PS    = 18000,        // tRP min: precharge to ACTIVATE/REFRESH
    parameter T_RC_PS    = 60000,        // tRC min: ACTIVATE to ACTIVATE, same bank
    parameter T_RFC_PS   = 60000,        // tRFC min: REFRESH to the next command
    parameter T_RAS_PS   = 42000,        // tRAS min: ACTIVATE to precharge
    parameter T_RAS_MAX_PS = 100_000_000,// tRAS max (100K ns)
    parameter T_RRD_PS   = 12000,        // tRRD min: ACTIVATE to ACTIVATE, different banks
    parameter T_WR_CK    = 2,            // tWR, clocks: last write data to precharge
    parameter T_MRD_CK   = 2,            // tMRD, clocks: mode register set to the next command
    parameter T_REFI_PS  = 15_625_000,   // 64 ms / 4096 rows (tREFI, "15.6 us" in the table)
    parameter T_PWRUP_PS = 200_000_000,  // Note 11: 200 us with a stable clock before the first command
    // The refresh rule is "every row within 64 ms": no REF_WINDOW consecutive refreshes may take longer
    // than REF_WINDOW * tREFI. 4096 is the datasheet rule. A smaller window is stricter (it rejects
    // burst refresh) and lets the check do something in a simulation of a few milliseconds.
    parameter REF_WINDOW = 4096,
    // ---- board delays (ps). ASSUMPTIONS: nothing is measured, and the builds have no I/O constraints ----
    //   T_CLK_DLY_PS  from the clock the controller puts on SDRAM_CLK (ideal PLL phase) to the clock at
    //                 the SDRAM: PLL output routing and output buffer, less the insertion delay of the
    //                 controller's own clock
    //   T_DQ_DLY_PS   from the SDRAM's data outputs to the controller's capture flip-flops: pad, input
    //                 buffer, routing
    //   T_OUT_DLY_PS  from the controller's flip-flops to the SDRAM pins: commands, addresses, DQM and
    //                 write data
    // 3 ns each: DS226-2.7E Table 3-18 gives at most 3.83 ns (C8/I7) from pin to pin through one LUT,
    // that is one input and one output path with next to no routing; the paths here add routing.
    parameter T_CLK_DLY_PS = 3000,
    parameter T_DQ_DLY_PS  = 3000,
    parameter T_OUT_DLY_PS = 3000,
    // 0: undefined read data are X. 1: pseudo-random bits instead, for benches whose RTL compares the
    // data (RTL takes X for a match and would miss the error).
    parameter UNDEF_RANDOM = 0,
    // 1: the first protocol error stops the simulation (for benches that do not read `errors`)
    parameter STRICT = 0
) (
    input  wire        clk,
    input  wire        cke,
    input  wire        ncs, nras, ncas, nwe,
    input  wire [1:0]  ba,
    input  wire [10:0] a,
    input  wire [3:0]  dqm,
    inout  wire [31:0] dq
);
    localparam MAX_MSGS = 20;
    localparam [63:0] REF_SPAN_PS = 64'd1 * T_REFI_PS * REF_WINDOW;

    reg [31:0] mem [0:(1<<AW)-1];
    // testbench peek port (cocotb cannot index large Icarus memories directly)
    reg  [AW-1:0] peek_addr = 0;
    wire [31:0]   peek_data = mem[peek_addr];
    // testbench hook: while high the model is unpowered and ignores the clock; at the falling edge it
    // starts afresh (state, counters, the 200 us pause; the memory array keeps its contents)
    reg           power_cycle = 1'b0;

    // ---- protocol errors (checked by the testbenches) ----
    integer errors;                      // all of the below
    integer e_row;                       // READ/WRITE with no open row in the bank
    integer e_state;                     // command illegal in this state, or during a burst
    integer e_cmd;                       // undefined or unmodelled command, mode or address
    integer e_init, e_pwrup;             // initialisation sequence, 200 us pause
    integer e_trcd, e_trp, e_trc, e_trfc, e_tras, e_trrd, e_twr, e_tmrd;
    integer e_refresh;                   // a row waited longer than the refresh interval allows
    integer e_setup, e_hold;             // tIS, tIH at the SDRAM pins
    integer e_tck;                       // clock period, high or low time
    integer e_dqx;                       // X or Z in write data
    integer e_bus;                       // DQ driven against the SDRAM's outputs
    integer refreshes;
    integer msgs;
    task fail(input [8*96:1] what);
        begin
            errors = errors + 1;
            if (msgs < MAX_MSGS) $display("%m: %0d ps: %0s", $time, what);
            else if (msgs == MAX_MSGS) $display("%m: further messages suppressed");
            msgs = msgs + 1;
            if (STRICT) begin
                $display("%m: STRICT is set, stopping the simulation");
                $finish;
            end
        end
    endtask

    // ---- the pins as the SDRAM sees them ----
    reg        clk_i = 1'b0;
    reg        cke_i, ncs_i, nras_i, ncas_i, nwe_i;
    reg [1:0]  ba_i;
    reg [10:0] a_i;
    reg [3:0]  dqm_i;
    reg [31:0] dq_i;
    always @(clk) clk_i <= #(T_CLK_DLY_PS) clk;
    always @(cke or ncs or nras or ncas or nwe)
        {cke_i, ncs_i, nras_i, ncas_i, nwe_i} <= #(T_OUT_DLY_PS) {cke, ncs, nras, ncas, nwe};
    always @(ba or a) {ba_i, a_i} <= #(T_OUT_DLY_PS) {ba, a};
    always @(dqm)     dqm_i <= #(T_OUT_DLY_PS) dqm;
    always @(dq)      dq_i  <= #(T_OUT_DLY_PS) dq;
    initial #0 begin                     // tied pins never produce an event
        {cke_i, ncs_i, nras_i, ncas_i, nwe_i} <= #(T_OUT_DLY_PS) {cke, ncs, nras, ncas, nwe};
        {ba_i, a_i} <= #(T_OUT_DLY_PS) {ba, a};
        dqm_i <= #(T_OUT_DLY_PS) dqm;
        dq_i  <= #(T_OUT_DLY_PS) dq;
    end

    // ---- data out: at the die, then as the controller's flip-flops see it ----
    reg [31:0] q_die;
    reg        oe_die = 1'b0;
    reg [31:0] q_pad;
    reg        oe_pad = 1'b0;
    always @(q_die or oe_die) {oe_pad, q_pad} <= #(T_DQ_DLY_PS) {oe_die, q_die};
    assign dq = oe_pad ? q_pad : 32'bz;

    reg [31:0] lfsr, undef;
    task next_undef;
        begin
            lfsr = lfsr ^ (lfsr << 13); lfsr = lfsr ^ (lfsr >> 17); lfsr = lfsr ^ (lfsr << 5);
            undef = UNDEF_RANDOM ? lfsr : 32'bx;
        end
    endtask

    // ---- state ----
    reg [2:0]  cas_lat;
    reg [3:0]  burst_len;
    reg        row_open [0:3];
    reg [10:0] row      [0:3];
    reg        act_seen [0:3], pre_seen [0:3], wr_seen [0:3], ap_pend [0:3];
    reg        unknown  [0:3];           // after power-on, until the first precharge: the bank may be in any state
    time       t_act    [0:3];           // last ACTIVATE
    time       t_pre    [0:3];           // start of the last precharge
    integer    ap_edge  [0:3];           // clock edge at which the auto precharge starts
    integer    wr_edge  [0:3];           // clock edge of the last write data word
    reg        rd_en    [0:15];          // read pipeline: word to put out at the following edges
    reg [31:0] rd_data  [0:15];
    reg        out_on;                   // a word was put out at the previous edge
    integer    rd_left;                  // edges until the read pipeline is empty
    reg [3:0]  dqm_prev;
    integer    wr_left, wr_addr, wr_bank;
    integer    edge_cnt, burst_end, mrs_edge, init_refs;
    reg        edge_seen, cmd_seen, mrs_seen, ref_seen, pre_all_seen, init_done, ref_late;
    time       t_power = 0, t_edge = 0, t_fall = 0, t_ref = 0, now = 0;
    time       t_cmd_chg = 0, t_adr_chg = 0, t_dqm_chg = 0, t_dq_chg = 0;
    reg        hold_cmd, hold_adr, hold_dqm, hold_dq;
    time       ref_ring [0:REF_WINDOW-1];
    integer    ref_idx;

    integer i;
    task power_up;
        begin
            errors = 0; e_row = 0; e_state = 0; e_cmd = 0; e_init = 0; e_pwrup = 0; e_trcd = 0; e_trp = 0;
            e_trc = 0; e_trfc = 0; e_tras = 0; e_trrd = 0; e_twr = 0; e_tmrd = 0; e_refresh = 0; e_setup = 0;
            e_hold = 0; e_tck = 0; e_dqx = 0; e_bus = 0; refreshes = 0; msgs = 0;
            cas_lat = 3'd2; burst_len = 4'd1; lfsr = 32'h2545F491;
            for (i = 0; i < 4; i = i + 1) begin
                row_open[i] = 0; act_seen[i] = 0; pre_seen[i] = 0; wr_seen[i] = 0; ap_pend[i] = 0; unknown[i] = 1;
            end
            for (i = 0; i < 16; i = i + 1) rd_en[i] = 0;
            out_on = 0; rd_left = 0; dqm_prev = 4'b0; wr_left = 0; edge_cnt = 0; burst_end = 0; init_refs = 0;
            edge_seen = 0; cmd_seen = 0; mrs_seen = 0; ref_seen = 0; pre_all_seen = 0; init_done = 0; ref_late = 0;
            hold_cmd = 0; hold_adr = 0; hold_dqm = 0; hold_dq = 0; ref_idx = 0;
            t_power = $time;
        end
    endtask
    initial power_up;
    always @(negedge power_cycle) power_up;

    function integer waddr(input [1:0] b, input [10:0] r, input [7:0] col);
        waddr = {b, r, col} & ((1 << AW) - 1);
    endfunction
    function integer next_in_burst(input integer adr);      // sequential burst: wraps inside the block
        next_in_burst = (adr & ~(burst_len - 1)) | ((adr + 1) & (burst_len - 1));
    endfunction

    task precharge(input integer b);                         // the bank's row closes now
        begin
            if (row_open[b]) begin
                if (now - t_act[b] < T_RAS_PS) begin e_tras = e_tras + 1; fail("tRAS: precharge too soon after ACTIVATE"); end
                if (now - t_act[b] > T_RAS_MAX_PS) begin e_tras = e_tras + 1; fail("tRAS max: row open for too long"); end
            end
            if (row_open[b] || unknown[b]) begin t_pre[b] = now; pre_seen[b] = 1; end
            row_open[b] = 0; unknown[b] = 0;
            ap_pend[b] = 0;
        end
    endtask

    task need_idle(input integer first, input integer last); // ACTIVATE: its bank; REFRESH, MODE REGISTER SET: all
        integer b;
        reg     open, early;
        begin
            open = 0; early = 0;
            for (b = first; b <= last; b = b + 1) begin
                if (row_open[b]) open = 1;
                else if (pre_seen[b] && now - t_pre[b] < T_RP_PS) early = 1;
            end
            if (open) begin e_state = e_state + 1; fail("command needs an idle bank, a row is open"); end
            if (early) begin e_trp = e_trp + 1; fail("tRP: command too soon after precharge"); end
        end
    endtask

    task write_word;
        reg [31:0] d;
        reg        bad;
        integer k;
        begin
            d = mem[wr_addr];
            bad = 0;
            for (k = 0; k < 4; k = k + 1) begin
                if (dqm_i[k] !== 1'b1) d[8*k +: 8] = dq_i[8*k +: 8];
                if (dqm_i[k] === 1'b0 && ^dq_i[8*k +: 8] === 1'bx) bad = 1;
                if (dqm_i[k] !== 1'b0 && dqm_i[k] !== 1'b1) begin d[8*k +: 8] = 8'bx; bad = 1; end
            end
            if (bad) begin e_dqx = e_dqx + 1; fail("write data or DQM undefined (X or Z)"); end
            mem[wr_addr] = d;
            if (dqm_i !== 4'b1111 && now - t_dq_chg < T_IS_PS) begin e_setup = e_setup + 1; fail("tIS: write data changed too close before the clock edge"); end
            if (now - t_dqm_chg < T_IS_PS) begin e_setup = e_setup + 1; fail("tIS: DQM changed too close before the clock edge"); end
            wr_addr = next_in_burst(wr_addr);
            wr_left = wr_left - 1;
            wr_edge[wr_bank] = edge_cnt; wr_seen[wr_bank] = 1;
        end
    endtask

    always @(negedge clk_i) if (clk_i === 1'b0) t_fall = $time;

    always @(posedge clk_i) begin : on_edge
        reg [2:0]  cmd;
        reg        live, use_adr, use_dq, adr_x;
        reg [31:0] q;
        integer    b, j, k;
        if (clk_i !== 1'b1 || power_cycle) disable on_edge;  // X at the start of a simulation is not an edge
        now = $time;
        live = (cke_i === 1'b1); use_adr = 0; use_dq = 0;

        // ---- clock ----
        if (edge_seen) begin
            if (now - t_edge < (cas_lat == 3'd3 ? T_CK3_PS : T_CK2_PS)) begin e_tck = e_tck + 1; fail("tCK: clock period too short for the CAS latency"); end
            else if (t_fall - t_edge < T_CH_PS || now - t_fall < T_CL_PS) begin e_tck = e_tck + 1; fail("tCH/tCL: clock high or low time too short"); end
        end

        if (cke_i === 1'b0) begin
            e_cmd = e_cmd + 1; fail("CKE low: clock suspend and power down are not modelled");
        end
        if (live) begin
            edge_cnt = edge_cnt + 1;

            // ---- refresh: the row due next has waited since ref_ring[ref_idx] ----
            if (init_done && !ref_late && now - ref_ring[ref_idx] > REF_SPAN_PS) begin
                ref_late = 1; e_refresh = e_refresh + 1; fail("refresh: a row waited longer than the refresh interval");
            end

            // ---- auto precharge that starts at this edge ----
            for (b = 0; b < 4; b = b + 1) if (ap_pend[b] && edge_cnt >= ap_edge[b]) precharge(b);

            // ---- read data: the word put out at this edge is valid tAC from now ----
            if (rd_en[0]) begin
                q = rd_data[0];
                for (k = 0; k < 4; k = k + 1) if (dqm_prev[k] !== 1'b0) q[8*k +: 8] = 8'bz;   // DQM latency 2
                next_undef;
                if (out_on) q_die <= #(T_OH_PS) undef;
                else begin q_die <= #(T_LZ_PS) undef; oe_die <= #(T_LZ_PS) 1'b1; end
                q_die <= #(cas_lat == 3'd3 ? T_AC3_PS : T_AC2_PS) q;
                out_on = 1;
            end else if (out_on) begin                       // the burst is over: tOH, then off by tHZ (= tAC)
                next_undef;
                q_die  <= #(T_OH_PS) undef;
                oe_die <= #(cas_lat == 3'd3 ? T_AC3_PS : T_AC2_PS) 1'b0;
                out_on = 0;
            end
            if (rd_left > 0) begin
                for (j = 0; j < 15; j = j + 1) begin rd_en[j] = rd_en[j+1]; rd_data[j] = rd_data[j+1]; end
                rd_en[15] = 0;
                rd_left = rd_left - 1;
            end

            // ---- write data: words 1.. of a burst ----
            if (wr_left > 0) begin write_word; use_dq = 1; end

            // ---- command ----
            cmd = {nras_i, ncas_i, nwe_i};
            if (^{ncs_i, cmd} === 1'bx) begin
                if (cmd_seen) begin e_cmd = e_cmd + 1; fail("command pins undefined"); end
            end else begin
                cmd_seen = 1;
                if (!ncs_i && cmd != 3'b111) begin
                    if (now - t_power < T_PWRUP_PS) begin e_pwrup = e_pwrup + 1; fail("power-up: command before the 200 us pause is over"); end
                    if (mrs_seen && edge_cnt - mrs_edge < T_MRD_CK) begin e_tmrd = e_tmrd + 1; fail("tMRD: command too soon after MODE REGISTER SET"); end
                    if (ref_seen && now - t_ref < T_RFC_PS) begin e_trfc = e_trfc + 1; fail("tRFC: command too soon after REFRESH"); end
                    if (edge_cnt <= burst_end) begin e_state = e_state + 1; fail("command during a burst (not modelled)"); end
                    else if (ap_pend[0] || ap_pend[1] || ap_pend[2] || ap_pend[3]) begin
                        e_state = e_state + 1; fail("command before the auto precharge of the last burst has started");
                    end
                    use_adr = (cmd != 3'b001 && cmd != 3'b110);
                    case (cmd)                               // the address bits this command reads
                    3'b000, 3'b011: adr_x = (^{ba_i, a_i} === 1'bx);
                    3'b100, 3'b101: adr_x = (^{ba_i, a_i[10], a_i[7:0]} === 1'bx);
                    3'b010:         adr_x = (a_i[10] === 1'bx) || (a_i[10] === 1'b0 && ^ba_i === 1'bx);
                    default:        adr_x = 0;
                    endcase
                    if (adr_x) begin e_cmd = e_cmd + 1; fail("address or bank undefined"); end
                    b = ba_i;
                    case (cmd)
                    3'b000: begin                            // MODE REGISTER SET
                        need_idle(0, 3);
                        if (a_i[6:4] != 3'd2 && a_i[6:4] != 3'd3) begin e_cmd = e_cmd + 1; fail("mode register: reserved CAS latency"); end
                        else cas_lat = a_i[6:4];
                        if (a_i[2]) begin e_cmd = e_cmd + 1; fail("mode register: burst length not modelled"); end
                        else burst_len = 4'd1 << a_i[1:0];
                        if (a_i[3] || a_i[10:7] != 4'b0 || ba_i != 2'b0) begin e_cmd = e_cmd + 1; fail("mode register: mode not modelled"); end
                        mrs_seen = 1; mrs_edge = edge_cnt;
                    end
                    3'b001: begin                            // AUTO REFRESH
                        need_idle(0, 3);
                        refreshes = refreshes + 1;
                        t_ref = now; ref_seen = 1;
                        if (!init_done) init_refs = init_refs + 1;
                        ref_ring[ref_idx] = now; ref_idx = (ref_idx + 1) % REF_WINDOW; ref_late = 0;
                    end
                    3'b010: begin                            // PRECHARGE, one bank or all
                        for (k = 0; k < 4; k = k + 1) if (a_i[10] || k == b) begin
                            if (row_open[k] && wr_seen[k] && edge_cnt - wr_edge[k] < T_WR_CK) begin e_twr = e_twr + 1; fail("tWR: precharge too soon after write data"); end
                            precharge(k);
                        end
                        if (a_i[10]) pre_all_seen = 1;
                    end
                    3'b011: begin                            // ACTIVATE
                        if (!init_done) begin e_init = e_init + 1; fail("initialisation: ACTIVATE before precharge all, 2 refreshes and mode register set"); end
                        need_idle(b, b);
                        if (act_seen[b] && now - t_act[b] < T_RC_PS) begin e_trc = e_trc + 1; fail("tRC: ACTIVATE too soon after ACTIVATE in the same bank"); end
                        for (k = 0; k < 4; k = k + 1)
                            if (k != b && act_seen[k] && now - t_act[k] < T_RRD_PS) begin e_trrd = e_trrd + 1; fail("tRRD: ACTIVATE too soon after ACTIVATE in another bank"); end
                        row_open[b] = 1; row[b] = a_i; t_act[b] = now; act_seen[b] = 1; wr_seen[b] = 0;
                    end
                    3'b100, 3'b101: begin                    // WRITE, READ
                        if (!row_open[b]) begin e_row = e_row + 1; fail("READ/WRITE: no open row in the bank"); end
                        else if (now - t_act[b] < T_RCD_PS) begin e_trcd = e_trcd + 1; fail("tRCD: READ/WRITE too soon after ACTIVATE"); end
                        burst_end = edge_cnt + burst_len - 1;
                        if (cmd == 3'b101) begin
                            for (j = 0; j < burst_len; j = j + 1) begin
                                k = (j == 0) ? waddr(b, row[b], a_i[7:0]) : next_in_burst(k);
                                rd_en[cas_lat - 2 + j]   = 1;
                                rd_data[cas_lat - 2 + j] = row_open[b] ? mem[k] : 32'bx;
                            end
                            rd_left = cas_lat - 1 + burst_len;
                            if (a_i[10]) begin ap_pend[b] = 1; ap_edge[b] = edge_cnt + burst_len; end
                        end else begin
                            if (row_open[b]) begin
                                wr_bank = b; wr_addr = waddr(b, row[b], a_i[7:0]); wr_left = burst_len;
                                write_word; use_dq = 1;                    // word 0 comes with the command
                            end
                            if (a_i[10]) begin ap_pend[b] = 1; ap_edge[b] = edge_cnt + burst_len - 1 + T_WR_CK; end
                        end
                    end
                    default: begin e_cmd = e_cmd + 1; fail("BURST STOP is not modelled"); end
                    endcase
                    if (!init_done && pre_all_seen && mrs_seen && init_refs >= 2) begin
                        init_done = 1;
                        for (j = 0; j < REF_WINDOW; j = j + 1) ref_ring[j] = now;
                    end
                end
            end

            // ---- set-up at this edge; the change detectors below check hold ----
            if (edge_seen) begin
                if (now - t_cmd_chg < T_IS_PS) begin e_setup = e_setup + 1; fail("tIS: command changed too close before the clock edge"); end
                if (use_adr && now - t_adr_chg < T_IS_PS) begin e_setup = e_setup + 1; fail("tIS: address changed too close before the clock edge"); end
            end
            dqm_prev = dqm_i;
        end
        hold_cmd = live && edge_seen; hold_adr = use_adr; hold_dq = use_dq; hold_dqm = use_dq;
        t_edge = now; edge_seen = 1;
    end

    always @(cke_i or ncs_i or nras_i or ncas_i or nwe_i) begin
        if (hold_cmd && $time - t_edge < T_IH_PS) begin e_hold = e_hold + 1; fail("tIH: command changed too soon after the clock edge"); end
        t_cmd_chg = $time;
    end
    always @(ba_i or a_i) begin
        if (hold_adr && $time - t_edge < T_IH_PS) begin e_hold = e_hold + 1; fail("tIH: address changed too soon after the clock edge"); end
        t_adr_chg = $time;
    end
    always @(dqm_i) begin
        if (hold_dqm && $time - t_edge < T_IH_PS) begin e_hold = e_hold + 1; fail("tIH: DQM changed too soon after the clock edge"); end
        t_dqm_chg = $time;
    end
    always @(dq_i) begin
        if (hold_dq && $time - t_edge < T_IH_PS) begin e_hold = e_hold + 1; fail("tIH: write data changed too soon after the clock edge"); end
        t_dq_chg = $time;
    end

    // ---- two drivers on DQ: the bus differs from what the SDRAM drives ----
    always @(dq or q_pad or oe_pad) begin
        #1;                                                  // let the bus settle
        if (oe_pad && ^q_pad !== 1'bx && dq !== q_pad) begin e_bus = e_bus + 1; fail("DQ driven against the SDRAM's read data"); end
    end
endmodule
`default_nettype wire
`timescale 1ns/1ps        // the unit the other simulation files are compiled with
