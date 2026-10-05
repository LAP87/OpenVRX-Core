"""TVP5150AM1 status registers 88h and 89h, bit by bit (TI SLES209E 3.21.49 and
3.21.50), for the tests that look at the status word {89h, 88h} which tvp_ctrl
delivers and the M3 probe prints as `st`.

Healthy NTSC reads 88h = 0Eh, healthy PAL 6Eh; 89h reads 00h or 10h (PAL also
20h or 30h). `healthy` says which bits make a word healthy and which may vary.
"""
ST1 = dict(peak_white=7, line_alternating=6, field_50hz=5, lost_lock=4, colour_lock=3, v_lock=2, h_lock=1, vcr=0)
ST2 = dict(weak_signal=6, pal_switch=5, odd_field=4, agc_frozen=3)     # bits 2:0: Macrovision detection


def decode(st):
    """Named bits of a status word {89h, 88h}."""
    s1, s2 = st & 0xFF, st >> 8
    out = {name: (s1 >> bit) & 1 for name, bit in ST1.items()}
    out.update({name: (s2 >> bit) & 1 for name, bit in ST2.items()})
    out['macrovision'] = s2 & 7
    return out


def healthy(st, standard):
    """True for the status of a locked input of the given standard ('ntsc' or 'pal') with
    no weak-signal flag. Not looked at, because they vary on a good signal: peak white,
    lost lock since the last read, TV/VCR, the field bit and the PAL switch."""
    d = decode(st)
    pal = int(standard == 'pal')
    return bool(d['h_lock'] and d['v_lock'] and d['colour_lock']
                and d['field_50hz'] == pal and d['line_alternating'] == pal
                and not d['weak_signal'] and not d['agc_frozen'] and d['macrovision'] == 0)
