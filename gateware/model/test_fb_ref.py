"""The reference for the field store and the display mapping (fb_ref.py) on its
own: the line mapping, the field phase from arrival times, and the promises
of the store on random sequences. The RTL is compared with these models in
sim/test_fb.py."""
import random
from collections import Counter

import pytest

import fb_ref as fb

FIELD, LINE = 1_081_000, 4118          # cycles at 64.8 MHz: an NTSC field and line


@pytest.mark.parametrize('lines, v', [(240, 720), (243, 720), (288, 720), (240, 1080), (288, 1080), (12, 36)])
def test_line_mapping(lines, v):
    up = [fb.src_line(j, lines, v) for j in range(v)]
    low = [fb.src_line(j, lines, v, low=True) for j in range(v)]
    assert up[0] == low[0] == 0 and up[-1] == low[-1] == lines - 1
    assert all(0 <= b - a <= 1 for seq in (up, low) for a, b in zip(seq, seq[1:])), 'no line skipped, none repeated later'
    assert all(0 <= u - w <= 1 for u, w in zip(up, low))
    # half a source line lower, as near as whole output lines allow (240 -> 720: one output line of three)
    assert 0.3 <= sum(up) / v - sum(low) / v <= 0.7, 'the lower field is drawn about half a source line lower'
    shown = Counter(up)
    assert {shown[s] for s in range(1, lines - 1)} <= {v // lines, v // lines + 1}, 'even line heights'


def phases(times, **kw):
    """(low, early, delay) for fields whose reference lines arrive at `times` (None: no reference line)."""
    ph, out = fb.FieldPhase(**kw), []
    for t in times:
        ph.new_field()
        early, dly = ph.ref(t) if t is not None else (False, 0)
        out.append((ph.low, early, dly))
    return out


def interlaced(n, jitter=0, seed=1):
    rng, t, out = random.Random(seed), 0, []
    for k in range(n):
        t += FIELD + (LINE // 2 if k % 2 else -(LINE // 2)) + rng.randint(-jitter, jitter)
        out.append(t)
    return out


def test_field_phase_interlaced():
    got = phases(interlaced(12))
    assert [low for low, _, _ in got[3:]] == [k % 2 == 1 for k in range(3, 12)], 'the field after the longer gap is the lower one'
    assert all(early == (not low) for low, early, _ in got[3:])
    assert all(abs(dly - LINE // 2) <= 1 for low, early, dly in got[3:] if early), 'delay: half a line period'


def test_field_phase_tolerates_jitter_and_a_missing_reference():
    times = interlaced(14, jitter=300)
    got = phases(times)
    assert [low for low, _, _ in got[3:]] == [k % 2 == 1 for k in range(3, 14)]
    assert all(abs(dly - LINE // 2) < 350 for low, early, dly in got[4:] if early)
    times[7] = None                         # that field has no reference line: the alternation carries on
    assert [low for low, _, _ in phases(times)[3:]] == [k % 2 == 1 for k in range(3, 14)]


def test_field_phase_not_interlaced():
    assert not any(low or early for low, early, _ in phases([k * FIELD for k in range(1, 10)]))
    # an interlaced source that becomes progressive is followed within two fields
    times = interlaced(8) + [interlaced(8)[-1] + k * FIELD for k in range(1, 8)]
    assert not any(low for low, _, _ in phases(times)[10:])


def test_field_phase_needs_its_window():
    """Negative control: if intervals a whole line apart count as equal, nothing is detected."""
    assert not any(low for low, _, _ in phases(interlaced(12), t_eq=5000, t_max=12000))


def store_run(seed, **kw):
    """Random fields (5 to 20 lines, some missing, some fields cut short), with frame starts and
    line requests in between. Checks at every step what the display relies on."""
    rng = random.Random(seed)
    st = fb.FieldStore(rt_hyst=2, **kw)
    t, shown_once, in_use = 0, False, set()

    def frame():
        nonlocal shown_once, in_use
        show, prev, _, rt = st.frame_start()
        shown_once = True
        in_use = {show} | ({prev} if prev is not None else set())
        seen = False
        for line in range(rng.randrange(8, 22)):
            buf, src = st.fetch(line)
            assert buf in in_use, 'read from a buffer that is neither shown nor the fallback'
            stored = src in st.ok[buf]
            assert stored or not seen, 'a line that is not stored was read although a stored one had been shown'
            seen = seen or stored

    for k in range(40):
        lines = rng.randrange(5, 21)
        for n in range(lines):
            if rng.random() < 0.15:
                continue
            t += rng.randrange(3000, 5000)
            if not st.have_field or st.is_new_field(k & 1, n):
                st.first_word(k & 1, n)
                assert not shown_once or st.cur not in in_use, 'the writer was given a buffer that is on screen'
            st.word(k & 1, n, 0, t)
            if rng.random() < 0.2:
                frame()
            st.line_stored(n)
            if rng.random() < 0.1:
                frame()
    return st


@pytest.mark.parametrize('seed', range(30))
def test_store_never_hands_out_what_is_on_screen(seed):
    store_run(seed)
    store_run(seed, rt_en=False)


def test_three_buffers_are_not_enough(monkeypatch):
    """Negative control: with three buffers the writer runs out of buffers that are neither
    on screen, nor the fallback, nor the one just published."""
    monkeypatch.setattr(fb, 'N_BUF', 3)
    failed = 0
    for seed in range(30):
        try:
            store_run(seed)
        except (AssertionError, StopIteration, IndexError):
            failed += 1
    assert failed > 20
