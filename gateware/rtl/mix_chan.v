// Mixer input stage for one channel (SDRAM/system clock domain): drains the
// channel's FIFO, writes line words into a 4-slot ring (4 x 512 x 32 bits,
// BSRAM) and keeps the metrics of each completed line. The mixer reads the
// oldest completed line (head) and releases it with pop_line.
//
// A line counts as bad when a timing code could not be decoded or its length
// (EAV to EAV) is not NTSC or PAL within LEN_TOL bytes, or while ext_bad is
// set (e.g. the decoder reports no horizontal/vertical lock).
// While ext_weak is set (M6: rssi_adc.v warns that this receiver's RSSI is low and the
// other's is not) every arriving line is `weak`: it counts as bad for this channel's health
// (`sick`, `self_well`), and line_mixer.v prefers the other receiver's good line in a pair,
// but the line itself is not bad: it is shown when it is the better or the only copy and is
// never left out for it. The mixer then leaves this receiver before its picture breaks up.
//
// A line is complete when its words 0..359 arrived in order since the last
// marker (a late SAV or a short active part gives fewer). An incomplete line is
// not stored, so the mixer never shows ring words left from an older line; it
// counts as bad for this channel's health, and it does not count as a line of
// this channel for the other one's `near` (that line was not delivered).
//
// Per line the mixer also gets (see line_mixer.v and model/line_mixer_ref.py):
//   age        system-clock cycles since the line was stored (saturates)
//   fc         this channel's field counter (mod 4); it advances when the
//              line number restarts or the F bit changes
//   self_well  this channel's last 8 lines, this one included, were all good
//   peer_sick  the other channel's last 8 lines were all bad when this line arrived
//   near       a line of the other channel arrived less than T_PAIR cycles before or
//              after this one (whatever its number)
// Health, field counter and `near` follow every arriving line, also one that is
// dropped because the ring is full.
`default_nettype none
module mix_chan #(
    parameter LEN_NTSC = 1716,
    parameter LEN_PAL  = 1728,
    parameter LEN_TOL  = 2,
    parameter TIMEOUT  = 262144,          // cycles without a line before `alive` drops (indicator only)
    parameter T_PAIR   = 1024,            // see line_mixer.v
    parameter AGE_W    = 13               // ages saturate; must reach well past T_PAIR
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        ext_bad,           // async, slow (decoder status)
    input  wire        ext_weak,          // async, slow (RSSI warning): health only
    input  wire        in_empty,
    input  wire [52:0] in_data,
    output wire        in_pop,

    input  wire        pop_line,
    input  wire [8:0]  rd_idx,
    output wire [31:0] rd_data,          // word rd_idx of the head line, 1 cycle after rd_idx

    input  wire        peer_sick,        // the other channel's `sick`, `arrived` and `last_age`
    input  wire        peer_arrived,
    input  wire [AGE_W-1:0] peer_last_age,
    output reg         sick,             // last 8 arrived lines all bad
    output wire        arrived,          // one cycle per arriving line
    output reg  [AGE_W-1:0] last_age,    // cycles since the last line arrived, minus one (saturates)

    output reg  [2:0]  count,            // completed lines waiting (0..4)
    output wire        head_field,
    output wire [9:0]  head_line,
    output wire [19:0] head_hf,
    output wire        head_bad,
    output wire        head_weak,
    output wire [1:0]  head_fc,
    output wire [AGE_W-1:0] head_age,
    output wire        head_peer_sick,
    output wire        head_self_well,
    output wire        head_near,
    output reg         alive,            // lines arrived within TIMEOUT (LEDs; the mixer does not use it)
    output reg         overflow          // sticky: a line was dropped because all slots were full
);
    localparam [AGE_W-1:0] AGE_MAX = {AGE_W{1'b1}};

    assign in_pop = !in_empty;
    wire is_marker = in_data[52];
    wire full = (count == 3'd4);

    reg [1:0] wslot, rslot;
    dual_clock_ram #(.DEPTH(2048), .AW(11), .W(32)) ring (
        .wclk(clk), .we(in_pop && !is_marker && !full), .waddr({wslot, in_data[40:32]}), .wdata(in_data[31:0]),
        .rclk(clk), .raddr({rslot, rd_idx}), .rdata(rd_data));

    wire [11:0] len = in_data[12:1];
    function in_tol(input [11:0] v, input [11:0] nominal);
        in_tol = (v + LEN_TOL >= nominal) && (v <= nominal + LEN_TOL);
    endfunction
    reg [1:0] ext_s, weak_s;
    always @(posedge clk) begin ext_s <= {ext_s[0], ext_bad}; weak_s <= {weak_s[0], ext_weak}; end

    // completeness: word indices 0, 1, .. 359 in order since the last marker
    reg  [8:0] w_next;                   // index the next word must carry
    reg        w_broken;
    wire [8:0] w_idx    = in_data[40:32];
    wire       complete = !w_broken && w_next == 9'd360;
    always @(posedge clk) begin
        if (in_pop && !is_marker) begin
            if (w_idx == 9'd0) begin w_next <= 9'd1; w_broken <= 1'b0; end      // a line's first word
            else if (w_idx == w_next) w_next <= w_next + 1'b1;
            else w_broken <= 1'b1;
        end
        if (in_pop && is_marker) begin w_next <= 9'd0; w_broken <= 1'b0; end
        if (rst) begin w_next <= 9'd0; w_broken <= 1'b0; end
    end
    wire bad_in = ext_s[1] || (in_data[20:17] != 4'd0) || !(in_tol(len, LEN_NTSC) || in_tol(len, LEN_PAL)) || !complete;

    reg                 m_field [0:3];
    reg [9:0]           m_line  [0:3];
    reg [19:0]          m_hf    [0:3];
    reg                 m_bad   [0:3];
    reg                 m_weak  [0:3];
    reg [1:0]           m_fc    [0:3];
    reg                 m_psick [0:3];
    reg                 m_swell [0:3];
    reg                 m_near  [0:3];
    reg [AGE_W-1:0]     m_age   [0:3];   // cycles since the line was stored, minus one
    assign head_field     = m_field[rslot];
    assign head_line      = m_line[rslot];
    assign head_hf        = m_hf[rslot];
    assign head_bad       = m_bad[rslot];
    assign head_weak      = m_weak[rslot];
    assign head_fc        = m_fc[rslot];
    assign head_age       = m_age[rslot];
    assign head_peer_sick = m_psick[rslot];
    assign head_self_well = m_swell[rslot];
    assign head_near      = m_near[rslot];

    // per-channel state that follows every arriving line
    wire        marker    = in_pop && is_marker;
    assign arrived = marker && complete;
    wire        m_fld     = in_data[51];
    wire [9:0]  m_ln      = in_data[50:41];
    reg         prev_valid, prev_field;
    reg  [9:0]  prev_line;
    reg  [1:0]  fc;
    wire        new_field = prev_valid && (m_ln <= prev_line || m_fld != prev_field);
    wire [1:0]  fc_n      = fc + {1'b0, new_field};
    reg  [7:0]  hist;                    // bad flags of the last 8 lines, newest in bit 0
    reg  [3:0]  hcnt;                    // lines seen, saturates at 8
    wire [7:0]  hist_n    = {hist[6:0], bad_in | weak_s[1]};   // health: bad, or weak (ext_weak)
    wire        hfull_n   = (hcnt >= 4'd7);
    wire        well_n    = hfull_n && (hist_n == 8'h00);
    wire        sick_n    = hfull_n && (hist_n == 8'hFF);

    // a line that lost words because the ring was full is not stored at all
    reg  skipping;
    wire mark = marker && complete && !full && !skipping;
    wire rel  = pop_line && count != 3'd0;
    reg [$clog2(TIMEOUT+1)-1:0] idle;
    integer i;
    always @(posedge clk) begin
        for (i = 0; i < 4; i = i + 1) begin
            if (m_age[i] != AGE_MAX) m_age[i] <= m_age[i] + 1'b1;
            if (peer_arrived && m_age[i] < T_PAIR - 1) m_near[i] <= 1'b1;    // the other channel's line came after this one
        end
        if (last_age != AGE_MAX) last_age <= last_age + 1'b1;

        if (in_pop && !is_marker && full) skipping <= 1'b1;
        if (marker) begin
            skipping   <= 1'b0;
            prev_valid <= 1'b1; prev_field <= m_fld; prev_line <= m_ln;
            fc   <= fc_n;
            hist <= hist_n;
            if (hcnt != 4'd8) hcnt <= hcnt + 1'b1;
            sick <= sick_n;
            if (complete) last_age <= 0;
            if (full || skipping) overflow <= 1'b1;
        end
        if (mark) begin
            m_field[wslot] <= m_fld;
            m_line[wslot]  <= m_ln;
            m_hf[wslot]    <= in_data[40:21];
            m_bad[wslot]   <= bad_in;
            m_weak[wslot]  <= weak_s[1];
            m_fc[wslot]    <= fc_n;
            m_psick[wslot] <= peer_sick;
            m_swell[wslot] <= well_n;
            m_near[wslot]  <= peer_arrived || (peer_last_age < T_PAIR - 1);   // ... or before it
            m_age[wslot]   <= 0;
            wslot <= wslot + 1'b1;
        end
        if (rel) rslot <= rslot + 1'b1;
        count <= count + {2'b00, mark} - {2'b00, rel};

        if (marker) begin idle <= 0; alive <= 1'b1; end
        else if (idle != TIMEOUT) idle <= idle + 1'b1;
        else alive <= 1'b0;

        if (rst) begin
            wslot <= 0; rslot <= 0; count <= 0; overflow <= 1'b0; idle <= 0; alive <= 1'b0;
            skipping <= 1'b0; prev_valid <= 1'b0; fc <= 0; hist <= 0; hcnt <= 0;
            sick <= 1'b0; last_age <= AGE_MAX;
        end
    end
endmodule
`default_nettype wire
