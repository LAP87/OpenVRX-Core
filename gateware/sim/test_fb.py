"""fb_backend (field store in SDRAM, display mapping, low-latency trigger)
against the reference in gateware/model/fb_ref.py.

tb_fb.v sends source lines the way the mixer does and logs, in order, what
the field store was asked and what it decided. This file replays the log
through the model: every decision must match (buffer shown, fallback, where
each line is read from, which buffer is written next, line count, field
phase). Independently of the model, every line read back must be a whole
line with the contents the store's own bookkeeping says, and what the
display puts on each output line must be the line it asked for.

The output frame is 40 lines of 1650 pixel clocks (884 us) as in test_m2.py;
source fields have 12 lines and a blanking gap, with periods chosen like
59.94 Hz and 50 Hz against a 60 Hz output.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_fb.py
"""
import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import fb_ref as fb  # noqa: E402

T_S, T_P, H_TOTAL = 15.4, 13.4, 1650
V_TOTAL, V_ACTIVE = 40, 36
OUT_LINE = H_TOTAL * T_P / T_S              # SDRAM clock cycles per output line (1436)
FRAME = V_TOTAL * OUT_LINE                  # 57 429 cycles
LINES, VBI = 12, 2
P_NTSC = FRAME * 1.001 / (LINES + VBI)      # line period: a field lasts 1.001 output frames (59.94 Hz into 60)
RT = dict(RT_NTSC=4, RT_HYST=2)             # thresholds that fit 12-line fields
T0 = 30000                                  # first line, cycles after reset (the SDRAM is ready by then)


def source(n_fields, period=P_NTSC, lines=LINES, vbi=VBI, interlaced=False, f_stuck=None, drop=(), cut=None, t0=T0):
    """[(start cycle, field bit, line, tag)]: n_fields fields, tag = field number + 1.
    interlaced: every other blanking gap is one line period longer. drop: {(field, line)} not sent.
    cut: {field: n} that field ends after n lines (the next one starts when it would have anyway)."""
    out, t = [], t0
    for k in range(n_fields):
        t += vbi * period + (period if interlaced and k % 2 else 0)
        for n in range(lines):
            if (k, n) not in drop and n < (cut or {}).get(k, lines):
                out.append((round(t + n * period), (k & 1) if f_stuck is None else f_stuck, n, k + 1))
        t += lines * period
    return out


def run_sim(name, src, alter=None, **params):
    """alter: {rtl file: (text, replacement)} compiles an altered copy (negative controls)."""
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    env = dict(os.environ)
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / 'lines.hex').write_text(''.join(f'{t << 23 | f << 22 | line << 12 | tag:014x}\n' for t, f, line, tag in src))
    p = dict(N_LINES=len(src), V_TOTAL=V_TOTAL, V_ACTIVE=V_ACTIVE, **RT)
    p.update(params)
    rtl = [GW / 'rtl' / n for n in ('async_fifo.v', 'sdram_burst.v', 'field_phase.v', 'fb_sdram.v', 'dual_clock_ram.v',
                                    'genlock_timing.v', 'ycbcr2rgb.v', 'cdc_sync.v', 'fb_display.v', 'fb_backend.v')]
    for fname, (old, new) in (alter or {}).items():
        text = (GW / 'rtl' / fname).read_text()
        assert text.count(old) == 1, f'{fname}: {old!r} not found once'
        (work / fname).write_text(text.replace(old, new))
        rtl = [work / fname if r.name == fname else r for r in rtl]
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_fb', *[f'-Ptb_fb.{k}={v}' for k, v in p.items()],
                    *map(str, rtl), str(HERE / 'sdram_model.v'), str(HERE / 'tb_fb.v')], cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    sd = [ln.split() for ln in (work / 'sd.txt').read_text().split('\n') if ln]
    pix = [ln.split() for ln in (work / 'pix.txt').read_text().split('\n') if ln]
    assert sd and sd[-1] == ['end', '0'], f'SDRAM protocol errors or no end: {sd[-1:]}'
    def num(x):
        return int(x) if x.isdigit() else -1          # x: read from SDRAM that was never written

    return [(r[0], *map(num, r[1:])) for r in sd[:-1]], [(r[0], *map(num, r[1:])) for r in pix]


class Frame:
    def __init__(self, show, prev, low, rt, cyc):
        self.show, self.prev, self.low, self.rt, self.cyc = show, prev, low, rt, cyc
        self.want, self.src, self.got = [], [], []      # lines asked for, (buffer, line) read, (tag, line) that came back
        self.tag = None                                 # field shown (its tag), None if nothing was stored yet
        self.lines = 0                                  # line count the display scales by (0: no field finished yet)


def replay(sd, src, **model_kw):
    """Run the model over the store's log. Returns (frames, model)."""
    st = fb.FieldStore(**{k.lower(): v for k, v in {**RT, **model_kw}.items()})
    tags = iter(src)
    cur_tag = None
    content = {}                    # (buffer, line) -> (tag, line) stored there, as the writer's marks say
    field_of = {}                   # buffer -> tag of the field it holds
    frames, pending = [Frame(0, None, False, False, 0)], []      # requests before the first frame start land here
    for ev, *v in sd:
        if ev == 'A':
            assert st.first_word(v[0], v[1]) == v[2]
            field_of[st.cur] = None
        elif ev == 'N':
            assert st.is_new_field(v[0], v[1]), f'published without a new field: {v}'
            assert (st.cur, (st.max_line + 1) & 1023) == (v[2], v[3]), f'published {v[2:4]}, model {st.cur, st.max_line + 1}'
            assert st.first_word(v[0], v[1]) == v[4], f'next buffer {v[4]}, model {st.cur}'
            content = {k: c for k, c in content.items() if k[0] != st.cur}
            field_of[st.cur] = None
        elif ev == 'J':
            assert st.end_joined(v[0], v[1]) == v[2], f'dropped joined field {v}, model {st.cur}'
            content = {k: c for k, c in content.items() if k[0] != st.cur}
            field_of[st.cur] = None
        elif ev == 'P':
            assert st.lines == v[0], f'line count {v[0]}, model {st.lines}'
        elif ev == 'W':
            t, f, line, tag = next(tags)
            assert (f, line) == (v[0], v[1]), f'word of line {v}, source says {(f, line)}'
            st.word(f, line, v[2], v[3])
            cur_tag = tag
        elif ev == 'M':
            st.line_stored(v[0])
            content[(st.cur, v[0])] = (cur_tag, v[0])
            field_of[st.cur] = cur_tag
        elif ev == 'D':
            show, prev, low, rt = st.frame_start()
            assert (show, st.prev, st.prev_ok, low, rt) == (v[0], v[1], bool(v[2]), bool(v[3]), bool(v[4])), \
                f'frame {len(frames)}: rtl {v[:5]}, model {(show, st.prev, st.prev_ok, low, rt)}'
            frames.append(Frame(show, prev, low, rt, v[5]))
            frames[-1].tag, frames[-1].lines = field_of.get(show), st.lines
        elif ev == 'F':
            frames[-1].want.append(v[0])
            pending.append(st.fetch(v[0]))
        elif ev == 'S':
            assert pending[0] == (v[0], v[1]), f'frame {len(frames) - 1} line {frames[-1].want[len(frames[-1].src)]}: ' \
                                               f'read from {v}, model {pending[0]}'
            frames[-1].src.append(pending.pop(0))
            frames[-1].stored = content.get((v[0], v[1]))
        elif ev == 'R':
            fr = frames[-1]
            if v[0] == -1:                              # a black line, written without reading the SDRAM
                assert fr.src[-1][0] == fb.BLANK, f'frame {len(frames) - 1}: black line where {fr.src[-1]} was due'
                assert v[3] == 0, f'frame {len(frames) - 1}: the black line for {fr.src[-1]} is not black'
                fr.got.append('blank')
                continue
            assert v[3] == 0, f'frame {len(frames) - 1}: line read from {fr.src[-1]} is not one whole line'
            # independent of the model: what is read must be a line the writer stored there
            assert fr.stored is not None, f'frame {len(frames) - 1}: read {fr.src[-1]}, which was never stored'
            assert (v[0], v[1]) == fr.stored, f'frame {len(frames) - 1}: {fr.src[-1]} holds {fr.stored}, read {v[:2]}'
            fr.got.append((v[0], v[1]))
    assert not pending
    return frames[1:], st


def settled(frames):
    """The frames that show a picture: from the first one after a field has finished (before
    that the display has no line count and no video) to the last but two (the source ends)."""
    return [fr for fr in frames if fr.lines][:-2]


def pix_frames(pix):
    """Per output frame: dict(pc, lines, video, low, src={y: source line}, shown={y: (tag, line, idx)})."""
    out = []
    for ev, *v in pix:
        if ev == 'V':
            out.append(dict(pc=v[0], lines=v[1], video=v[2], low=None, src={}, shown={}))
        elif out and ev == 'B':
            out[-1]['low'] = v[0]
        elif out and ev == 'Y':
            out[-1]['src'][v[0]] = v[1]
        elif out and ev == 'X':
            out[-1]['shown'][v[0]] = tuple(v[1:])
    return [f for f in out if len(f['src']) == V_ACTIVE]


def check_display(frames, pixf):
    """Every complete output frame with video: the source line of each output line follows the
    model, and the word on the line is word 52 of the line that the store read for it."""
    by_time = {}
    for fr in frames:
        by_time[round(fr.cyc * T_S / T_P)] = fr
    checked = 0
    for pf in pixf:
        if not pf['video']:
            continue
        # the frame's first request went out one output line before its first line
        near = [fr for pc, fr in by_time.items() if abs(pc - (pf['pc'] - H_TOTAL)) < 40]
        assert len(near) == 1, f"no frame decision at pixel clock {pf['pc'] - H_TOTAL}"
        fr = near[0]
        assert pf['low'] == fr.low
        for y in range(V_ACTIVE):
            s = fb.src_line(y, pf['lines'], V_ACTIVE, pf['low'])
            assert pf['src'][y] == s, f"output line {y}: source line {pf['src'][y]}, model {s}"
            assert s in fr.want, f'line {s} was never asked for'
            got = fr.got[fr.want.index(s)]
            if got == 'blank':
                assert pf['shown'][y] == BLACK_FIELDS, f"output line {y}: shows {pf['shown'][y]}, not the black line"
            else:
                assert pf['shown'][y] == (*got, 52), f"output line {y}: shows {pf['shown'][y]}, the store read {got}"
            checked += 1
    return checked


# the black word as the pixel log prints it: bits 30:19, 18:9, 8:0
BLACK_FIELDS = (fb.BLACK_WORD >> 19 & 0xFFF, fb.BLACK_WORD >> 9 & 0x3FF, fb.BLACK_WORD & 0x1FF)


def unknown_in_video(pix):
    """Output frames with video on which a word read from the line buffer had an X/Z bit."""
    return [f for f in pix_frames(pix) if f['video'] and any(-1 in w for w in f['shown'].values())]


def fresh(frames, src):
    """Top-line latency of each frame in cycles: frame start minus the start of line 0 of the field shown."""
    t_line0 = {tag: t for t, _, line, tag in src if line == 0}
    return [fr.cyc - t_line0[fr.tag] for fr in frames if fr.tag in t_line0]


# ---- buffered mode
P_SLOW = FRAME * 1.05 / (LINES + VBI)       # 5 % slow: the output frame start moves 0.7 lines up the field per frame
FIELD_SLOW = (LINES + VBI) * P_SLOW


def test_shows_the_field_being_written():
    """A source 5 % slower than the output, so that the frame start passes every position in
    the field. Decisions match the model and everything read is whole. Each frame shows the
    newest field that is far enough along: the top line is never older than one field period
    plus the lead the writer must have, and often only a few lines old."""
    src = source(18, period=P_SLOW)
    sd, pix = run_sim('tb_fb', src)
    frames, st = replay(sd, src)
    assert check_display(frames, pix_frames(pix)) > 10 * V_ACTIVE
    live = settled(frames)
    assert len(live) >= 12
    assert all(fr.src == [(fr.show, n) for n in fr.want] for fr in live), 'a line was not read from the field shown'
    tags = [fr.tag for fr in live]
    assert tags == sorted(tags) and len(set(tags)) >= len(tags) - 2, f'fields shown: {tags}'
    lat = fresh(live, src)
    lead = (RT['RT_NTSC'] + RT['RT_HYST'] + 1) * P_SLOW
    assert max(lat) < FIELD_SLOW + lead and min(lat) < lead, [round(x / FIELD_SLOW, 2) for x in lat]
    assert sum(fr.rt for fr in live) > len(live) // 2


def test_finished_fields_only_is_a_field_slower():
    """Negative control for the latency: with RT_EN = 0 a frame shows the latest finished
    field, and the same source gives a top line that is one to two field periods old."""
    src = source(18, period=P_SLOW)
    sd, pix = run_sim('tb_fb_rt0', src, RT_EN=0)
    frames, st = replay(sd, src, RT_EN=0)
    check_display(frames, pix_frames(pix))
    live = settled(frames)
    lat = fresh(live, src)
    assert not any(fr.rt for fr in frames)
    assert min(lat) > FIELD_SLOW - VBI * P_SLOW and max(lat) > 1.7 * FIELD_SLOW, [round(x / FIELD_SLOW, 2) for x in lat]


def test_source_faster_than_output():
    """Fields 0.5 % shorter than output frames (a camera above 60 Hz): two fields can end
    within one frame. Review 2026-10-05 V-3: the triple buffer then gave the writer the buffer
    on screen. Here every line read is whole and from the field shown or its fallback."""
    src = source(12, period=FRAME * 0.995 / (LINES + VBI))
    sd, pix = run_sim('tb_fb_fast', src)
    frames, st = replay(sd, src)
    assert check_display(frames, pix_frames(pix)) > 5 * V_ACTIVE
    live = settled(frames)
    assert len(live) >= 8 and all(fr.src == [(fr.show, n) for n in fr.want] for fr in live)
    assert all(g == (fr.tag, n) for fr in live for n, g in zip(fr.want, fr.got)), 'a frame shows one field, whole'


FIRST_MISSING = {(1, 0)}                     # line 0 of the first field the store keeps (field 0 is joined)
OLD_FALLBACK = ("else begin f_src <= f_line; f_blank <= 1'b1; rep_v <= 1'b0; end",
                "else begin f_buf <= show_buf; f_src <= f_line; rep_buf <= show_buf; rep_line <= f_line; end")


@pytest.mark.parametrize('rt', [0, 1])
def test_missing_first_line_is_black(rt):
    """Line 0 missing from the first field the store publishes: there is no line above and no
    fallback field, so the store writes a black line instead of reading a line that was never
    stored (review 2026-10-06, F3: frames with video then had unknown line buffer words).
    Decisions match the model, every line read was stored, the black line is shown black."""
    src = source(5, drop=FIRST_MISSING)
    sd, pix = run_sim(f'tb_fb_first_missing_{rt}', src, RT_EN=rt, TAIL=1_000_000)
    frames, st = replay(sd, src, RT_EN=rt)
    check_display(frames, pix_frames(pix))
    assert not unknown_in_video(pix), 'a frame with video shows words that were never written'
    black = [f for f in pix_frames(pix) if f['video'] and BLACK_FIELDS in f['shown'].values()]
    assert black, 'no frame with video showed the black line'


def test_missing_first_line_old_fallback_reads_unwritten():
    """Negative control: with the earlier fallback (read the missing line from the shown buffer)
    a frame with video shows unknown words again."""
    src = source(5, drop=FIRST_MISSING)
    sd, pix = run_sim('tb_fb_first_missing_old', src, alter={'fb_sdram.v': OLD_FALLBACK}, RT_EN=0, TAIL=1_000_000)
    assert unknown_in_video(pix)


def test_missing_lines_are_covered():
    """Lines 4 and 5, then 7 to 10, are missing from one field, and line 3 from the next. A
    single line or a pair is replaced by the line above; from the third missing line on the
    previous field's line is used. Nothing older or half-written reaches the display."""
    drop = {(4, 4), (4, 5), (4, 7), (4, 8), (4, 9), (4, 10), (5, 3)}
    src = source(9, drop=drop)
    sd, pix = run_sim('tb_fb_gaps', src, RT_EN=0)
    frames, st = replay(sd, src, RT_EN=0)
    assert check_display(frames, pix_frames(pix)) > 5 * V_ACTIVE
    hit = [fr for fr in frames if fr.tag == 5]
    assert hit, 'field 4 (tag 5) was never shown'
    for fr in hit:
        got = dict(zip(fr.want, fr.got))
        assert [got[n] for n in (3, 4, 5, 6)] == [(5, 3), (5, 3), (5, 3), (5, 6)], 'a pair of lines: the line above'
        assert [got[n] for n in (7, 8, 9, 10, 11)] == [(5, 6), (5, 6), (4, 9), (4, 10), (5, 11)], 'then the field before'
    for fr in [fr for fr in frames if fr.tag == 6]:
        got = dict(zip(fr.want, fr.got))
        assert (got[2], got[3], got[4]) == ((6, 2), (6, 2), (6, 4))


def mixer_left_out(bad_both, n_fields=9):
    """{(field, line)} that the mixer model leaves out of n_fields fields of two receivers in step
    whose lines `bad_both` are bad on both (model/line_mixer_ref.py, lines bad on both receivers)."""
    import bt656
    import line_mixer_ref as mix
    m, ev = mix.Mixer(keep_words=False), []
    for k in range(n_fields):
        for n in range(LINES):
            t = (k * (LINES + VBI) + VBI + n) * 63_556.0
            for ch in (0, 1):
                ev.append((t + 3000.0 * ch, ch, bt656.LineRecord(k & 1, n, 1716, 1440, 0, int((k, n) in bad_both), 1000)))
    for t, ch, rec in ev:
        m.push(ch, rec, t)
    m.finish()
    left, fld, prev = set(), 0, -1
    for (_, _, _, line), o in zip(m.trace, m.omitted):
        fld += line < prev
        prev = line
        if o:
            left.add((fld, line))
    return left


def test_lines_the_mixer_leaves_out_are_covered():
    """Lines bad on both receivers that the mixer leaves out: field 4 line 5, the first line of
    field 5, the last line of field 6, and of field 7's lines 3 and 4 the first. The store
    replaces a line with the line above, a first line with the field before's line. No black
    line (that is only for a first line without a field before, review 2026-10-06 F3) and no gap.
    A left-out last line is not replaced: for the store that field is one line shorter, and the
    picture is scaled from LINES - 1 lines while it is one of the two latest fields."""
    drop = mixer_left_out({(4, 5), (5, 0), (6, LINES - 1), (7, 3), (7, 4)})
    assert drop == {(4, 5), (5, 0), (6, LINES - 1), (7, 3)}, drop
    src = source(9, drop=drop)
    sd, pix = run_sim('tb_fb_left_out', src, RT_EN=0)
    frames, st = replay(sd, src, RT_EN=0)
    assert check_display(frames, pix_frames(pix)) > 5 * V_ACTIVE
    assert not unknown_in_video(pix)
    last = [fr for fr in frames if fr.tag == 7]
    assert last and all(fr.lines == LINES - 1 and max(fr.want) == LINES - 2 and fr.got == [(7, n) for n in fr.want]
                        for fr in last), [(fr.lines, fr.got) for fr in last]
    want = {5: {4: (5, 4), 5: (5, 4), 6: (5, 6)}, 6: {0: (5, 0), 1: (6, 1)}, 8: {3: (8, 2), 4: (8, 4)}}
    for tag, lines in want.items():
        hit = [fr for fr in frames if fr.tag == tag]
        assert hit, f'field {tag - 1} (tag {tag}) was never shown'
        for fr in hit:
            got = dict(zip(fr.want, fr.got))
            assert {n: got[n] for n in lines} == lines, f'tag {tag}: {got}'
            assert 'blank' not in fr.got, f'tag {tag}: a black line'


def test_short_field_does_not_change_the_scale():
    """Field 4 ends after 5 lines. The display keeps scaling by 12 lines (it used to
    stretch 5 lines over the screen); the rest of that frame comes from the field before."""
    src = source(9, cut={4: 5})
    sd, pix = run_sim('tb_fb_cut', src, RT_EN=0)
    frames, st = replay(sd, src, RT_EN=0)
    pf = pix_frames(pix)
    check_display(frames, pf)
    assert {f['lines'] for f in pf if f['video']} == {LINES}
    hit = [fr for fr in frames if fr.tag == 5]
    assert hit and all([g[0] for g in fr.got] == [5] * 5 + [5, 5] + [4] * 5 for fr in hit), [fr.got for fr in hit]


def test_field_phase_from_arrival_times():
    """An interlaced source with the F bit stuck at 1: every other field arrives one line
    period later. That field is drawn half a source line lower. Then the same source without
    interlace: no offset."""
    src = source(9, interlaced=True, f_stuck=1)
    sd, pix = run_sim('tb_fb_il', src, RT_EN=0)
    frames, st = replay(sd, src, RT_EN=0)
    pf = pix_frames(pix)
    check_display(frames, pf)
    low = {fr.tag: fr.low for fr in frames if fr.tag}
    assert [low[t] for t in range(4, 9)] == [True, False, True, False, True], low
    assert {(f['low'], f['src'][4]) for f in pf if f['video']} == {(0, 1), (1, 0)}, 'output line 4: line 1, or still line 0 in the lower field'
    sd, pix = run_sim('tb_fb_prog', source(7, f_stuck=1), RT_EN=0)
    frames, st = replay(sd, source(7, f_stuck=1), RT_EN=0)
    assert not any(fr.low for fr in frames)


# The store leaves reset at about cycle 1056 in tb_fb (sdram_burst's 1000-cycle wait at SDRAM_FREQ
# 5 MHz, then the mode register). With the first field's line 1 at T0 + 3 line periods, this T0 puts
# it 53 390 cycles after that: 4096 cycles less than one field period, in the middle of the window
# (2 T_EQ .. T_MAX) in which field_phase.v takes two intervals for an interlaced pair.
FIRST_REF_T0 = 42124
PHASE_FIX = "if (rst) begin cnt <= {W{1'b1}};"


def test_first_interval_is_not_measured():
    """A progressive source whose first reference line comes about 4096 cycles less than a field
    period after the store leaves reset. field_phase.v counted that time as an interval between
    two fields, took the next field for the lower one of an interlaced pair and drew it half a
    line lower (found by sim/test_fuzz_chain.py, seed 17). The count now starts saturated, as in
    the model: the first reference line is not a measurement. Decisions match the model and no
    frame is drawn lower."""
    src = source(6, t0=FIRST_REF_T0)
    sd, pix = run_sim('tb_fb_first_ref', src, RT_EN=0)
    frames, st = replay(sd, src, RT_EN=0)
    check_display(frames, pix_frames(pix))
    assert not any(fr.low for fr in frames) and not any(r[4] for r in sd if r[0] == 'D')


def test_first_interval_check_is_tested():
    """Negative control: field_phase.v counting from 0 after reset draws a frame of the same
    source lower, and disagrees with the model."""
    src = source(6, t0=FIRST_REF_T0)
    sd, pix = run_sim('tb_fb_first_ref_old', src, alter={'field_phase.v': (PHASE_FIX, 'if (rst) begin cnt <= 0;')}, RT_EN=0)
    assert any(r[4] for r in sd if r[0] == 'D'), 'the old counter did not draw any frame lower'
    with pytest.raises(AssertionError, match='rtl'):
        replay(sd, src, RT_EN=0)


def test_slow_source_needs_the_longer_lead():
    """A source at two thirds of the output rate with 14-line fields: the output reads a
    field much faster than it arrives (a PAL field into a 60 Hz output, exaggerated). With a
    lead of 7 lines for such fields the display never reaches the writer. Negative control:
    with a lead of 2 lines it does, and the lines the writer has not reached are covered from
    the field before; they are still whole lines."""
    period = FRAME * 1.5 / 17
    src = source(10, period=period, lines=14, vbi=3)
    for lead, caught in ((7, False), (2, True)):
        kw = dict(RT_SPLIT=13, RT_PAL=lead)
        sd, pix = run_sim(f'tb_fb_slow{lead}', src, **kw)
        frames, st = replay(sd, src, **kw)
        check_display(frames, pix_frames(pix))
        live = settled(frames)
        assert any(fr.rt for fr in live)
        behind = [fr for fr in live if fr.rt and fr.src != [(fr.show, n) for n in fr.want]]
        assert bool(behind) == caught, f'lead {lead}: {len(behind)} frames caught up with the writer'


# ---- low-latency mode
def ll_run(name, src, **params):
    """Returns (frame triggers [(cycle, lower field)], complete output frames from pix_frames,
    lengths in lines of all output frames once the first field has arrived)."""
    sd, pix = run_sim(name, src, LL=1, **params)
    ph, trig, exp = fb.FieldPhase(), [], []
    for ev, *v in sd:
        if ev == 'G':
            ph.new_field()
        elif ev == 'E':
            _, line, cyc, fire = v
            early, dly = ph.ref(cyc) if line == 1 else (False, 0)
            if fire:
                exp.append((cyc + 2 + dly if (early and params.get('LL_EQ', 1)) else cyc + 1, ph.low))
        elif ev == 'T':
            trig.append((v[0], bool(v[1])))
    assert trig == exp[:len(trig)] and len(trig) >= 10, f'triggers {trig[:6]}, model {exp[:6]}'
    starts = [v[0] for ev, *v in pix if ev == 'V' and v[2]]
    return trig, pix_frames(pix), [round((b - a) / H_TOTAL) for a, b in zip(starts, starts[1:])][:-2]


def ll_picture(frames, first_tag, last_tag):
    """The frames showing fields first_tag..last_tag: each shows one field, the next one each
    time, every output line the source line the model gives, read from the ring intact."""
    k = next(i for i, f in enumerate(frames) if f['shown'][V_ACTIVE - 1][0] == first_tag)
    out = frames[k:k + last_tag - first_tag + 1]
    for n, f in enumerate(out):
        for y in range(V_ACTIVE):
            s = fb.src_line(y, f['lines'], V_ACTIVE, f['low'])
            assert f['src'][y] == s and f['shown'][y] == (first_tag + n, s, 52), \
                f"frame {k + n} line {y}: source line {f['src'][y]} shows {f['shown'][y]}, expected line {s} of field {first_tag + n}"
    return out


def lengths(frames):
    return [round((b['pc'] - a['pc']) / H_TOTAL) for a, b in zip(frames, frames[1:])]


# Low-latency runs use a frame of 48 lines with 10 lines of back porch: the timing generator
# takes a trigger anywhere in the vertical blanking, and 720p has 25 lines of that.
LL_V = dict(V_TOTAL=48)
P_LL = 48 * OUT_LINE * 1.001 / 13.5         # 13.5 source lines per field: 3.56 output lines per source line


def test_low_latency_frames_are_equally_long():
    """Low-latency mode with an interlaced source: the fields arrive 13 and 14 line periods
    apart in turn. The frame start of the early field is delayed by half a line period and
    the late field is drawn half a source line lower; the output frames then differ by at
    most one line. Negative control (LL_EQ = 0): they alternate between 47 and 50 lines."""
    src = source(14, period=P_LL, lines=9, vbi=4, interlaced=True)
    trig, frames, _ = ll_run('tb_fb_ll', src, **LL_V)
    assert [low for _, low in trig[3:]] == [k % 2 == 1 for k in range(3, len(trig))], 'every other field is the lower one'
    locked = ll_picture(frames, 4, 13)
    assert [f['low'] for f in locked[:4]] == [1, 0, 1, 0]
    # after the start the output is a few lines behind and catches up with frames of 47 lines
    assert set(lengths(locked)) <= {47, 48, 49} and set(lengths(locked)[-5:]) <= {48, 49}, lengths(locked)
    trig0, frames0, _ = ll_run('tb_fb_ll0', src, LL_EQ=0, **LL_V)
    lens0 = lengths(ll_picture(frames0, 4, 13))[-5:]
    assert max(lens0) - min(lens0) >= 2, lens0


def test_low_latency_field_without_its_reference_line():
    """Line 1 of one field is missing: its frame starts a line late (after line 2) and there
    is no arrival time to measure. The field keeps the phase the alternation predicts, the
    output catches up with frames one line short of nominal, never shorter, and the fields
    before and after it are shown intact."""
    src = source(14, period=P_LL, lines=9, vbi=4, interlaced=True, drop={(7, 1)})
    trig, frames, _ = ll_run('tb_fb_ll_noref', src, **LL_V)
    assert [low for _, low in trig[3:]] == [k % 2 == 1 for k in range(3, len(trig))]
    before = ll_picture(frames, 5, 7)
    ll_picture(frames, 9, 13)
    k = frames.index(before[-1])
    lens = lengths(frames[k:k + 7])
    assert max(lens) in (51, 52) and min(lens) == 47 and lens[-1] in (48, 49), lens


def test_low_latency_false_field_start_does_not_cut_the_frame():
    """The line numbers restart in the middle of field 7 (as when the mixer changes to a
    receiver that is out of step): a frame trigger in the middle of the output frame. It is
    ignored; no frame is shorter than 47 lines and the fields after it are shown intact.
    Negative control (JUMP_AFTER = 1, as it used to be): the frame is cut short."""
    src = [(t, f, n if (tag != 8 or n < 5) else n - 5, tag)
           for t, f, n, tag in source(14, period=P_LL, lines=9, vbi=4, interlaced=True)]
    trig, frames, lens = ll_run('tb_fb_ll_false', src, **LL_V)
    ll_picture(frames, 5, 7)
    ll_picture(frames, 9, 13)
    assert min(lens) >= 47, lens
    trig1, frames1, lens1 = ll_run('tb_fb_ll_false1', src, JUMP_AFTER=1, **LL_V)
    assert min(lens1) < 40, lens1


def test_low_latency_source_moves():
    """From field 7 on every field comes 0.4 field periods later (another camera, a receiver
    that locked elsewhere). The first early triggers are ignored; after the third the output
    realigns with one short frame, and the fields after that are shown intact."""
    field = 13.5 * P_LL
    src = [(t + (round(0.4 * field) if tag >= 8 else 0), f, n, tag)
           for t, f, n, tag in source(16, period=P_LL, lines=9, vbi=4, interlaced=True)]
    trig, frames, lens = ll_run('tb_fb_ll_move', src, **LL_V)
    ll_picture(frames, 5, 7)
    ll_picture(frames, 12, 15)
    assert sum(1 for n in lens if n < 47) <= 1 and max(lens) <= 47 + 8, lens


# ---- switching between the modes while video runs
MAX_WAIT = 8                                # genlock_timing.v default: a frame waits at most this many extra lines
VT = LL_V['V_TOTAL']                        # the switching runs use the low-latency frame of 48 lines
MS_FIELDS = 19
FIELD_CYC = 13.5 * P_LL
MS_SW1 = round(T0 + 5.55 * FIELD_CYC)       # BUF -> LOW in field 5 (tag 6): the writer joins it after its line 2
MS_SW2 = round(T0 + 11.85 * FIELD_CYC)      # LOW -> BUF in field 11 (tag 12), late in the field
MS_SRC = source(MS_FIELDS, period=P_LL, lines=9, vbi=4, interlaced=True)


@functools.lru_cache(maxsize=None)
def switch_run(name, **params):
    """Run MS_SRC with ll_mode 0, then 1 at MS_SW1 and 0 at MS_SW2 (tb_fb.v drives it).
    Returns what the output did: the switch times, complete output frames, vsync starts,
    frame starts and the lines with an X/Z (all in pixel clocks)."""
    sd, pix = run_sim(name, MS_SRC, SW1=MS_SW1, SW2=MS_SW2, **LL_V, **params)
    mode = [(v[0], v[1]) for ev, *v in pix if ev == 'M']
    assert [m for _, m in mode] == [1, 0], f'mode switches seen at the output: {mode}'
    return dict(sw=[pc for pc, _ in mode], frames=pix_frames(pix), vs=[v[0] for ev, *v in pix if ev == 'S'],
                bad=[v[0] for ev, *v in pix if ev == 'Z'], starts=[v[0] for ev, *v in pix if ev == 'V'])


def cur_field(pc):
    """Tag of the newest field whose line 1 was complete at pixel clock pc."""
    cyc = pc * T_P / T_S
    return max(tag for t, _, line, tag in MS_SRC if line == 1 and t + 360 <= cyc)


def check_switch(run):
    """The checks of the mode switch. Returns {check: [what is wrong]}, all empty if the switch is clean."""
    sw1, sw2 = run['sw']
    frames, starts, vs = run['frames'], run['starts'], run['vs']
    bad = dict(xz=[], length=[], picture=[], settle=[])
    # 1. No X/Z on r, g, b, de, hsync, vsync, except at the very start and from a switch to
    #    the end of the first output frame after it (the line ring holds nothing yet).
    allowed = [(0, starts[2])] + [(sw, [s for s in starts if s > sw][1]) for sw in (sw1, sw2)]
    bad['xz'] = [round(pc / H_TOTAL, 1) for pc in run['bad'] if not any(a <= pc < b for a, b in allowed)]
    # 2. Frame length from vsync to vsync: VT - 1 .. VT + MAX_WAIT (genlock_timing.v, formal/genlock_props.v);
    #    VT - 1 .. VT + 1 (750/751-line frames) from the third frame after a switch on.
    for a, b in zip(vs, vs[1:]):
        n = round((b - a) / H_TOTAL)
        settling = any(sw < b <= sw + 3 * (VT + MAX_WAIT) * H_TOTAL for sw in (sw1, sw2))
        if not (VT - 1 <= n <= (VT + MAX_WAIT if settling else VT + 1)):
            bad['length'].append((round(b / H_TOTAL), n))
    # 3. The picture. Every output line is the source line the model gives, a whole line (word 52).
    lines_ok = lambda f: all(f['shown'][y][1:] == (fb.src_line(y, f['lines'], V_ACTIVE, f['low']), 52) for y in range(V_ACTIVE))
    tags = lambda f: sorted({f['shown'][y][0] for y in range(V_ACTIVE)})
    pre = [f for f in frames if f['pc'] + VT * H_TOTAL <= sw1 and f['video']][1:]
    low = [f for f in frames if f['pc'] > sw1 and f['pc'] + VT * H_TOTAL <= sw2][1:]    # not the first frame after the switch
    buf = [f for f in frames if f['pc'] > sw2]
    for name, group in (('BUF before', pre), ('LOW', low)):
        for f in group:                                         # one field per frame
            if not (f['video'] and lines_ok(f) and len(tags(f)) == 1):
                bad['picture'].append((name, round(f['pc'] / H_TOTAL), tags(f)))
    lt = [tags(f)[0] for f in low]
    if len(lt) < 4 or lt != list(range(lt[0], lt[0] + len(lt))):
        bad['picture'].append(('LOW fields are not consecutive', lt))
    for f in low:                                               # and the newest one
        if not 0 <= cur_field(f['pc']) - tags(f)[0] <= 1:
            bad['picture'].append(('LOW shows an old field', round(f['pc'] / H_TOTAL), tags(f), cur_field(f['pc'])))
    # Back in BUF: the first two frames are what the store has (lines not yet written are replaced
    # by an earlier line, fb_sdram.v): word 52 of a line that is the one wanted or above it. From the
    # third frame on every line is the right one, one field per frame, no more than two fields old.
    for i, f in enumerate(buf):
        if i < 2:
            if f['video'] and not all(f['shown'][y][2] == 52 and 0 <= f['shown'][y][1] <= f['src'][y] for y in range(V_ACTIVE)):
                bad['picture'].append(('BUF after: line below the one wanted', round(f['pc'] / H_TOTAL)))
        elif not (f['video'] and lines_ok(f) and len(tags(f)) == 1 and tags(f)[0] >= cur_field(f['pc']) - 2):
            bad['settle'].append(('BUF after', i, round(f['pc'] / H_TOTAL), tags(f), cur_field(f['pc'])))
    if len(buf) < 6:
        bad['settle'].append(('too few frames after the switch back', len(buf)))
    return bad


def test_mode_switch_buf_low_buf():
    """ll_mode goes to 1 in the middle of a field and back to 0 late in a field while the source
    runs (interlaced, 59.94 Hz-like; 5 fields BUF, 6 LOW, 7 BUF). Checked at the output:
      * no X/Z on r, g, b, de, hsync, vsync after the first frame following each switch;
      * every frame, vsync to vsync, has VT - 1 .. VT + 8 lines (genlock_timing.v), and
        VT - 1 .. VT + 1 from the third frame after a switch; no SDRAM protocol error (run_sim);
      * BUF -> LOW: the first frame after the switch has no video (have_video = 0: the writer
        joined the field in the middle, so the frame trigger has not come yet); every later
        frame is one whole field, one field after the other, the newest;
      * LOW -> BUF: the frames before the first publish after the switch have no video
        (fb_display.v forgets the fields published before low-latency mode); no frame shows a
        field older than two fields; from the third frame on every line is the right one and
        every frame is one field. The LOW frame in progress at the switch ends with what the
        line buffer holds (not checked).
    Negative control for the no-stale-frame check: without the `if (ll) have_pub <= 0` line in
    fb_display.v, or with the joined field published as before (fb_sdram.v `joined`), the first
    frame after LOW -> BUF shows the field that sat in buffer 0 before (7 fields old in this
    run); run once by hand with each of the two taken out."""
    run = switch_run('tb_fb_ms')
    bad = check_switch(run)
    assert not any(bad.values()), bad
    sw1, sw2 = run['sw']
    assert not next(f for f in run['frames'] if f['pc'] > sw1)['video'], 'the first frame after BUF -> LOW had video'
    after = [f for f in run['frames'] if f['pc'] > sw2]
    assert not after[0]['video'], 'the first frame after LOW -> BUF had video before a field was published'
    old = [f for f in after if f['video'] and min(f['shown'][y][0] for y in range(V_ACTIVE)) < cur_field(f['pc']) - 2]
    assert not old, 'stale frame after LOW -> BUF: ' + str([f['pc'] for f in old])


def test_mode_switch_checks_catch_faults():
    """Negative control for test_mode_switch_buf_low_buf: the same run with faults made in the
    test bench (not the RTL), each of which the matching check must catch. Fault 1: one word
    of field 9, shown in LOW, carries the wrong tag (picture). Fault 2: r is X for one pixel
    clock in a LOW frame (X/Z). Fault 3: an extra vsync pulse in a BUF frame after the second
    switch (frame length). The run without faults passes the same checks."""
    clean = switch_run('tb_fb_ms_ref')     # own build directory: the two tests may run in separate processes at once
    assert not any(check_switch(clean).values())
    fr = clean['frames']
    pc_low = fr[next(i for i, f in enumerate(fr) if f['pc'] > clean['sw'][0]) + 3]['pc'] + 10 * H_TOTAL + 500
    pc_buf = fr[-3]['pc'] + 5 * H_TOTAL
    run = switch_run('tb_fb_ms_fault', FAULT=7, FAULT_TAG=9, FAULT_PC=pc_low, FAULT_PC2=pc_buf)
    bad = check_switch(run)
    assert bad['xz'], 'an X on r was not seen'
    assert bad['length'], 'an extra vsync pulse was not seen'
    assert [b for b in bad['picture'] if b[0] == 'LOW'], f"a wrong tag was not seen: {bad['picture']}"
