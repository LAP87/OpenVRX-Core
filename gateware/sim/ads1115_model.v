// Behavioural TI ADS1115 (16-bit I2C ADC) as an I2C target, written from TI SBAS444E:
// section 7.5.2 (a write is the Address Pointer byte, then the register MSB and LSB;
// a read returns the MSB and the LSB of the register P[1:0] selects), 7.5.3 (P[1:0]
// stays until the next write), table 8-3 (Config register, reset 8583h).
//
// Modelled: P[1:0] = 00b conversion register (read only), 01b config, 10b/11b the
// thresholds (stored, no comparator). Single-shot mode only: writing the config with
// OS = 1 and MODE = 1 while no conversion runs starts one; it takes 1 / DR (DR[2:0]
// of that write) plus 25 us wake-up, and then the conversion register holds the code
// of the selected input. OS reads 0 while a conversion runs (table 8-3). A write
// with OS = 1 during a conversion has no effect on it. MODE = 0 (continuous) is not
// modelled: such a write is logged and starts nothing.
//
// Inputs: ain_uv[0..3] (microvolts, set by the testbench). The input is sampled when
// the conversion ends. Only MUX 100b..111b (AINx against GND) are modelled; the
// differential settings give code 0. Code = trunc(uV * 32768 / FSR_uV), clamped to
// 8000h..7FFFh (LSB = FSR / 2^15, table 7-1).
//
// Testbench hooks: absent (no ACK at all, as with no ADC fitted), conversions (count).
`timescale 1ns/1ps
module ads1115_model #(
    parameter [6:0] ADDR = 7'h48,
    parameter LOG = 0
) (
    input  wire scl,
    input  wire sda,
    output reg  sda_low
);
    reg [15:0] cfg, conv, lo_t, hi_t, snap;
    reg [1:0]  ptr;
    reg [7:0]  sh, msb;
    integer    bitc, phase, nbyte;
    reg        active, reading, me, send, master_ack;
    reg        absent, converting;
    integer    conversions;
    integer    ain_uv [0:3];
    reg [2:0]  c_mux, c_pga, c_dr;
    integer    i;

    function integer fsr_uv(input [2:0] pga);
        case (pga)
            3'd0: fsr_uv = 6_144_000; 3'd1: fsr_uv = 4_096_000; 3'd2: fsr_uv = 2_048_000;
            3'd3: fsr_uv = 1_024_000; 3'd4: fsr_uv = 512_000; default: fsr_uv = 256_000;
        endcase
    endfunction
    function integer sps(input [2:0] dr);
        case (dr)
            3'd0: sps = 8; 3'd1: sps = 16; 3'd2: sps = 32; 3'd3: sps = 64;
            3'd4: sps = 128; 3'd5: sps = 250; 3'd6: sps = 475; default: sps = 860;
        endcase
    endfunction
    function [15:0] code(input integer uv, input [2:0] pga);
        reg signed [63:0] c;
        begin
            c = uv;
            c = (c * 32768) / fsr_uv(pga);               // truncates toward zero
            if (c > 32767) c = 32767;
            if (c < -32768) c = -32768;
            code = c[15:0];
        end
    endfunction

    initial begin
        cfg = 16'h8583; conv = 16'h0000; lo_t = 16'h8000; hi_t = 16'h7FFF; ptr = 2'd0;
        sda_low = 0; active = 0; absent = 0; converting = 0; conversions = 0;
        for (i = 0; i < 4; i = i + 1) ain_uv[i] = 0;
    end

    // ---- single-shot conversion
    event go;
    always @(go) begin
        converting = 1;
        conversions = conversions + 1;
        #(1.0e9 / sps(c_dr) + 25_000.0);
        conv = c_mux[2] ? code(ain_uv[c_mux[1:0]], c_pga) : 16'h0000;
        if (LOG) $display("ADC C %0d %04x", c_mux, conv);
        converting = 0;
    end
    task commit(input [15:0] v);
        begin
            if (LOG) $display("ADC W %0d %04x", ptr, v);
            case (ptr)
                2'd1: begin
                    cfg = v;
                    if (v[15] && v[8] && !converting) begin
                        c_mux = v[14:12]; c_pga = v[11:9]; c_dr = v[7:5];
                        -> go;
                    end
                    if (!v[8]) $display("ADC continuous mode is not modelled");
                end
                2'd2: lo_t = v;
                2'd3: hi_t = v;
                default: ;                                   // the conversion register is read only
            endcase
        end
    endtask
    function [15:0] reg_read(input [1:0] p);
        case (p)
            2'd0: reg_read = conv;
            2'd1: reg_read = {!converting, cfg[14:0]};
            2'd2: reg_read = lo_t;
            default: reg_read = hi_t;
        endcase
    endfunction

    // ---- I2C target (the bit engine of i2c_slave_model.v)
    always @(negedge sda) if (scl === 1'b1) begin          // START / repeated START
        active = 1; bitc = 0; phase = 0; reading = 0; me = 0; send = 0; sda_low = 0; nbyte = 0;
    end
    always @(posedge sda) if (scl === 1'b1) begin          // STOP
        active = 0; sda_low = 0;
    end
    always @(posedge scl) if (active) begin
        if (bitc < 8) begin
            if (!reading) sh = {sh[6:0], sda};
            bitc = bitc + 1;
        end else if (bitc == 8) begin
            if (reading) master_ack = (sda === 1'b0);
            bitc = 9;
        end
    end
    always @(negedge scl) if (active) begin
        if (bitc == 8) begin                                // byte complete: ACK slot
            if (reading) sda_low = 0;                       // the controller answers
            else if (phase == 0) begin
                me = (sh[7:1] == ADDR) && !absent; reading = sh[0]; send = sh[0] && me;
                sda_low = me; phase = 1;
            end else if (me) begin
                sda_low = 1;
                if (phase == 1) begin ptr = sh[1:0]; phase = 2; end
                else if (phase == 2) begin msb = sh; phase = 3; end
                else if (phase == 3) begin commit({msb, sh}); phase = 4; end
            end
        end else if (bitc == 9) begin                       // ACK slot over
            bitc = 0; sda_low = 0;
            if (reading && phase > 1) send = master_ack && me;   // only the addressed target goes on sending
            if (reading) phase = 2;
            if (reading && send) begin
                if (nbyte == 0) snap = reg_read(ptr);
                sh = (nbyte == 0) ? snap[15:8] : (nbyte == 1) ? snap[7:0] : 8'hFF;
                if (LOG && nbyte == 1) $display("ADC R %0d %04x", ptr, snap);
                nbyte = nbyte + 1;
                sda_low = !sh[7];
            end
        end else if (reading && send) begin
            sda_low = !sh[7 - bitc];
        end
    end
endmodule
