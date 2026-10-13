// i2c_master against i2c_slave_model: single- and multi-byte writes, NACK in the
// middle of a write, writes to an absent address, read-back. A bus monitor
// (independent of the slave) prints what is on SCL/SDA:
//   BUS S | BUS P | BUS B <byte> <ack bit: 0 ACK, 1 NACK>
// and every transaction ends with DONE <nack> <wreq pulses> <stuck>, reads with RD <data>.
// A slave holding SCL low is modelled by `hold`: briefly (stretch) and for good (stuck).
// The next write byte is put on wdata a varying number of clocks after each wreq.
// Driven by sim/test_i2c_master.py, which compares everything with model/i2c_ref.py.
`timescale 1ns/1ps
`default_nettype none
module tb_i2c_master;
    parameter AUTO_INC = 1;               // 0: negative control, a slave that does not auto-increment
    parameter STRETCH_MAX = 200;          // clocks the master waits for SCL before it gives up
    parameter READ_BYTES = 1;             // 2: every read takes two bytes
    localparam DIV = 4;

    reg clk = 0, rst = 1;
    always #5 clk = ~clk;

    reg        start = 0, rw = 0;
    reg  [6:0] dev = 0;
    reg  [7:0] addr = 0, wdata = 0, wextra = 0;
    wire       wreq, busy, done, nack, stuck, scl_low, m_sda_low, s_sda_low;
    wire [8*READ_BYTES-1:0] rdata;
    reg        hold = 0;                  // a slave holds SCL low
    wire scl = (scl_low | hold) ? 1'b0 : 1'b1;
    wire sda = (m_sda_low | s_sda_low) ? 1'b0 : 1'b1;
    i2c_master #(.DIV(DIV), .STRETCH_MAX(STRETCH_MAX), .READ_BYTES(READ_BYTES)) dut (.clk(clk), .rst(rst), .start(start), .rw(rw),
        .dev(dev), .addr(addr), .wdata(wdata), .wextra(wextra), .wreq(wreq), .busy(busy), .done(done), .nack(nack),
        .stuck(stuck), .rdata(rdata),
        .scl_low(scl_low), .sda_low(m_sda_low), .scl_in(scl), .sda_in(sda));
    i2c_slave_model #(.ADDR(7'h5C), .LOG(1), .AUTO_INC(AUTO_INC)) slave (.scl(scl), .sda(sda), .sda_low(s_sda_low));

    // ---- bus monitor
    integer nb = 0;
    reg [8:0] bits;
    always @(negedge sda) if (scl === 1'b1 && !rst) begin $display("BUS S"); nb = 0; end
    always @(posedge sda) if (scl === 1'b1 && !rst) $display("BUS P");
    always @(posedge scl) if (!rst) begin
        bits = {bits[7:0], sda};
        nb = nb + 1;
        if (nb == 9) begin $display("BUS B %02x %0d", bits[8:1], bits[0]); nb = 0; end
    end

    // ---- transactions
    reg [7:0] buf_ [0:255];
    integer   n_req = 0, i, lag = -1;
    always @(posedge clk) begin
        if (lag == 0) wdata <= buf_[n_req];
        if (lag >= 0) lag <= lag - 1;
        if (wreq) begin
            n_req = n_req + 1;
            lag <= (n_req * 37) % (30 * DIV);          // 0 .. 119 clocks; the master allows 35 x DIV
        end
    end

    task wr(input [6:0] d, input [7:0] r, input integer n, input integer nack_at);
        begin
            slave.nack_data = nack_at;
            n_req = 0;
            @(posedge clk);
            dev <= d; addr <= r; rw <= 1'b0; wdata <= buf_[0]; wextra <= n - 1; start <= 1'b1;
            @(posedge clk); start <= 1'b0;
            @(posedge done);
            @(posedge clk);
            $display("DONE %0d %0d %0d", nack, n_req, stuck);
            repeat (20) @(posedge clk);
        end
    endtask
    task rd(input [6:0] d, input [7:0] r);
        begin
            slave.nack_data = -1;
            @(posedge clk);
            dev <= d; addr <= r; rw <= 1'b1; wextra <= 8'd0; start <= 1'b1;
            @(posedge clk); start <= 1'b0;
            @(posedge done);
            @(posedge clk);
            $display("RD %0x", rdata);
            $display("DONE %0d 0 %0d", nack, stuck);
            repeat (20) @(posedge clk);
        end
    endtask
    // a write during which a slave holds SCL low for `len` clocks (len < 0: until the master gives up),
    // starting at the first time the master pulls SCL low `after` clocks or more after the start
    reg     seen_done = 0;
    integer held;
    always @(posedge clk) if (done) seen_done <= 1'b1;
    task wr_hold(input [6:0] d, input [7:0] r, input integer n, input integer after, input integer len);
        begin
            slave.nack_data = -1;
            n_req = 0; seen_done = 0;
            @(posedge clk);
            dev <= d; addr <= r; rw <= 1'b0; wdata <= buf_[0]; wextra <= n - 1; start <= 1'b1;
            @(posedge clk); start <= 1'b0;
            repeat (after) @(posedge clk);
            @(posedge scl_low);
            hold = 1; held = 0;
            while (!seen_done && (len < 0 ? held < 5 * STRETCH_MAX : held < len)) begin
                @(posedge clk); held = held + 1;
            end
            if (len < 0) $display("HELD %0d", held);
            hold = 0;
            while (!seen_done && held < 5 * STRETCH_MAX) begin @(posedge clk); held = held + 1; end
            @(posedge clk);
            if (seen_done) $display("DONE %0d %0d %0d", nack, n_req, stuck);
            else $display("HUNG busy=%0d", busy);
            repeat (100) @(posedge clk);
        end
    endtask
    task fill(input integer n, input integer seed);
        for (i = 0; i < n; i = i + 1) buf_[i] = (i * 29 + seed) & 8'hFF;
    endtask

    initial begin
        repeat (5) @(posedge clk);
        rst <= 1'b0;
        repeat (5) @(posedge clk);
        $display("T one");        fill(1, 8'hA5);   wr(7'h5C, 8'h10, 1, -1);
        $display("T two");        fill(2, 8'h11);   wr(7'h5C, 8'h20, 2, -1);
        $display("T eight");      fill(8, 8'h31);   wr(7'h5C, 8'h30, 8, -1);
        $display("T nack_mid");   fill(8, 8'h57);   wr(7'h5C, 8'h40, 8, 3);
        $display("T absent_multi"); fill(2, 8'h66); wr(7'h5D, 8'h50, 2, -1);
        $display("T absent_one"); fill(1, 8'h77);   wr(7'h5D, 8'h60, 1, -1);
        $display("T nack_first"); fill(4, 8'h0C);   wr(7'h5C, 8'h68, 4, 0);
        $display("T read");       rd(7'h5C, 8'h10); rd(7'h5C, 8'h21); rd(7'h5C, 8'h30); rd(7'h5C, 8'h37);
                                  rd(7'h5C, 8'h42); rd(7'h5C, 8'h43); rd(7'h5C, 8'h68); rd(7'h5D, 8'h10);
        $display("T full");       fill(256, 8'h03); wr(7'h5C, 8'hA0, 256, -1);
        $display("T read2");      rd(7'h5C, 8'hA0); rd(7'h5C, 8'hFF); rd(7'h5C, 8'h00); rd(7'h5C, 8'h9F);
        $display("T stretch");    fill(2, 8'h44);   wr_hold(7'h5C, 8'hB0, 2, 300, STRETCH_MAX - 50);
        $display("T stuck");      fill(2, 8'h55);   wr_hold(7'h5C, 8'hC0, 2, 20, -1);
        $display("T after_stuck"); fill(1, 8'h99);  wr(7'h5C, 8'hD0, 1, -1); rd(7'h5C, 8'hD0); rd(7'h5C, 8'hB1);
        $display("END");
        $finish;
    end
    initial begin #50_000_000 $display("TIMEOUT"); $finish; end
endmodule
`default_nettype wire
