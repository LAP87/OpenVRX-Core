// Which decoder's lines the mixer is to treat as bad (mixer2 ext_bad), from tvp_ctrl's status:
// every line of a decoder is bad unless its last poll round was whole and read horizontal and
// vertical lock (88h bits 1 and 2). Unknown status counts as bad: no round yet, a round with a
// NACK, a re-initialisation (status_valid 0). Until 2026-10-21 (task 51) only a valid status
// without lock was bad, so a free-running decoder's lines, which arrive in step and with a
// flat picture, could win the mixer's pairs while its status was unknown (hub
// docs/design/2026-10-21/LOGIKGRANSKNING.md F4). A lone decoder is still shown: the mixer shows
// lines bad on both receivers when they come in a row. Used by M4 and M6; the same combinational
// expression as before, so it reaches mixer2's synchronisers as it did (F14 is separate).
`default_nettype none
module dec_bad (
    input  wire [1:0]  status_valid,      // tvp_ctrl
    input  wire [15:0] status0, status1,  // {89h, 88h}
    output wire [1:0]  bad                // [0] decoder A, [1] decoder B
);
    assign bad = {!(status_valid[1] && status1[1] && status1[2]),
                  !(status_valid[0] && status0[1] && status0[2])};
endmodule
`default_nettype wire
