"""The integer mixer rule (line_mixer_ref) must make the same choices as the
float prototype mixer/line_mixer.py for the same per-line noise values, and
the whole mixer model must keep its promises on randomised line sequences:
a complete picture while one receiver has it, nothing from an unlocked
receiver, no mixing of receivers that are out of step. (The RTL is compared
with this model line for line in sim/test_mixer.py.)"""
import random
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / 'mixer'))
import bt656  # noqa: E402
import line_mixer  # noqa: E402  (the float prototype)
import line_mixer_ref as ref  # noqa: E402


def frames_with_noise(noise):
    """Frames whose line_noise() is exactly `noise` (width 2: [0, e])."""
    f = np.zeros(noise.shape + (2,), np.float32)
    f[..., 1] = noise
    return f


def test_integer_rule_matches_prototype():
    rng = np.random.default_rng(7)
    # mix of similar and very different values so blend, stay and switch all occur
    base = rng.integers(0, 20000, size=(30, 40))
    na = base + rng.integers(-3000, 3000, size=base.shape)
    nb = base + rng.integers(-3000, 3000, size=base.shape)
    na[5:8], nb[12:14] = na[5:8] * 4, nb[12:14] * 4          # bursts of snow
    na, nb = np.clip(na, 0, None), np.clip(nb, 0, None)
    na[0, :3] = nb[0, :3] = 0                                # both zero -> blend
    _, choice = line_mixer.mix(frames_with_noise(na), frames_with_noise(nb),
                               blend_margin=38 / 256, switch_margin=0.25)
    cur, got = 0, np.empty_like(choice)
    for f in range(na.shape[0]):
        for y in range(na.shape[1]):
            use, cur = ref.decide_pair(int(na[f, y]), int(nb[f, y]), cur)
            got[f, y] = {ref.USE_A: 0, ref.USE_B: 1, ref.USE_BLEND: 2}[use]
    assert (got == choice).all(), np.argwhere(got != choice)[:5]
    assert {0, 1, 2} <= set(np.unique(got).tolist())


def test_bad_line_loses():
    assert ref.decide_pair(10, 99999, 1, bad_a=False, bad_b=True) == (ref.USE_A, 0)
    assert ref.decide_pair(10, 99999, 0, bad_a=True, bad_b=False) == (ref.USE_B, 1)
    assert ref.decide_pair(10, 99999, 1, bad_a=True, bad_b=True) == (ref.USE_B, 1)
    # weak RSSI: between two good lines the weak receiver loses, whatever the snow says; a bad line still loses
    assert ref.decide_pair(10, 99999, 0, weak_a=True) == (ref.USE_B, 1)
    assert ref.decide_pair(99999, 10, 1, weak_b=True) == (ref.USE_A, 0)
    assert ref.decide_pair(10, 10, 0, weak_a=True) == (ref.USE_B, 1), 'no blend with a weak receiver'
    assert ref.decide_pair(10, 10, 0, weak_a=True, weak_b=True) == (ref.USE_BLEND, 0), 'both weak: as before'
    assert ref.decide_pair(10, 99999, 0, bad_b=True, weak_a=True) == (ref.USE_A, 0), 'weak but good beats bad'


# ---- the whole mixer on synthetic line sequences
LINE_NS = 63_556.0                  # NTSC line period
VBI, LINES, FIELDS = 22, 40, 6      # line periods without lines, lines per field, fields per run
FIELD_NS = (VBI + LINES) * LINE_NS
SEEDS = range(25)


def receiver(rng, t0=0.0, fields=FIELDS, lost=(), bad=(), shift=None):
    """[(t_ns, record)] of one receiver. lost / bad: sets of (field, line). shift: {field: k},
    the receiver numbers the lines of that field k too high. No pixel data (the mixer reads zeros)."""
    out = []
    for fld in range(fields):
        for n in range(LINES):
            if (fld, n) not in lost:
                t = t0 + fld * FIELD_NS + (VBI + n) * LINE_NS + rng.uniform(-150, 150)
                rec = bt656.LineRecord(fld & 1, n + (shift or {}).get(fld, 0), 1716, 1440, 0, int((fld, n) in bad),
                                       rng.choice((900, 1000, 1100, 5000, 20000)))
                out.append((t, rec))
    return out


def run(ra, rb, **kw):
    m = ref.Mixer(keep_words=False, **kw)
    for t, ch, rec in sorted([(t, 0, r) for t, r in ra] + [(t, 1, r) for t, r in rb], key=lambda e: e[:2]):
        m.push(ch, rec, t)
    m.finish()
    assert not m.overflow
    return m


def out_fields(trace):
    """Shown lines split the way the frame buffer splits them: [[line, ...]]."""
    fields, f_prev = [], None
    for use, _, f, line in trace:
        if use:
            if not fields or f != f_prev or line <= fields[-1][-1]:
                fields.append([])
            fields[-1].append(line)
            f_prev = f
    return fields


def spots(rng, n):
    """n places (field, line), at least 7 lines apart, away from the first and last lines."""
    places = [(f, k) for f in range(FIELDS) for k in range(5, LINES - 5, 10)]
    return [(f, k + rng.randrange(4)) for f, k in rng.sample(places, n)]


def out_of_step(rng):
    """A time offset of less than a field that keeps every line of one receiver out of the
    other's pairing window or, with whole lines, puts them next to lines with other numbers."""
    return rng.choice((rng.uniform(0.3, 0.7), rng.randrange(1, VBI + LINES) + rng.uniform(0.3, 0.7),
                       rng.randrange(1, VBI + LINES) + rng.uniform(-0.05, 0.05))) * LINE_NS


DAMAGE = [('a', ''), ('b', ''), ('', 'a'), ('', 'b'), ('ab', ''), ('', 'ab'), ('a', 'b'), ('b', 'a')]   # (lost on, bad on)


def in_step_every_good_line_is_shown_once(seed, **kw):
    """Receivers in step, isolated damage on either or both: a line is shown, once and in
    order, whenever a receiver delivered it undamaged, and the damaged copy is never the one
    taken."""
    rng = random.Random(seed)
    lost, bad = (set(), set()), (set(), set())
    for place in spots(rng, 14):
        lost_on, bad_on = rng.choice(DAMAGE)
        for ch, name in enumerate('ab'):
            if name in lost_on:
                lost[ch].add(place)
            if name in bad_on:
                bad[ch].add(place)
    m = run(receiver(rng, 0.0, lost=lost[0], bad=bad[0]), receiver(rng, rng.uniform(-5000, 5000), lost=lost[1], bad=bad[1]), **kw)
    fld, prev, seen = 0, -1, [[] for _ in range(FIELDS)]
    for use, pop, _, line in m.trace:
        fld += line < prev
        prev = line
        good = [(fld, line) not in lost[ch] and (fld, line) not in bad[ch] for ch in (0, 1)]
        if use:
            seen[fld].append(line)
            if any(good):
                assert all(good[ch] for ch in (0, 1) if use >> ch & 1), f'damaged copy used: field {fld} line {line}'
    for fld in range(FIELDS):
        must = [n for n in range(LINES) if any((fld, n) not in lost[ch] | bad[ch] for ch in (0, 1))]
        may = [n for n in range(LINES) if any((fld, n) not in lost[ch] for ch in (0, 1))]
        assert seen[fld] == sorted(set(seen[fld])) and set(must) <= set(seen[fld]) <= set(may), f'field {fld}: {seen[fld]}'
    assert len(out_fields(m.trace)) == FIELDS


def burst_loss_on_one_receiver_loses_nothing(seed, **kw):
    """Receivers in step; one of them delivers nothing for up to a field and a half, starting
    anywhere (also across a blanking interval). The other one has every line: all are shown."""
    rng = random.Random(seed)
    ch, first, length = rng.randrange(2), rng.randrange(LINES, (FIELDS - 2) * LINES), rng.randrange(1, 60)
    gone = {divmod(k, LINES) for k in range(first, first + length)}
    rx = [receiver(rng, 0.0, lost=gone if ch == 0 else ()), receiver(rng, rng.uniform(-5000, 5000), lost=gone if ch == 1 else ())]
    m = run(*rx, **kw)
    assert out_fields(m.trace) == [list(range(LINES))] * FIELDS
    assert all(u for u, p, *_ in m.trace if p == 0b11 or p == 2 >> ch), 'no line of the complete receiver is dropped'


def unlocked_receiver_is_not_shown(seed, **kw):
    """One decoder reports no lock all the time and runs in step or out of step with the
    other, which is good apart from isolated lost lines. After a start-up of at most 16 lines
    of the good receiver, every one of its lines is shown and none of the other's."""
    rng = random.Random(seed)
    sick = rng.randrange(2)
    offset = rng.choice((rng.uniform(-5000, 5000), out_of_step(rng), FIELD_NS / 2 + rng.uniform(-5000, 5000)))
    good_rx = receiver(rng, FIELD_NS, lost=set(spots(rng, 6)))
    sick_rx = receiver(rng, FIELD_NS - offset, fields=FIELDS + 1)
    m = run(*(good_rx, sick_rx)[::-1 if sick == 0 else 1], ext_bad=(sick == 0, sick == 1), **kw)
    n_good = 0
    for i, (use, pop, _, line) in enumerate(m.trace):
        n_good += bool(pop & (2 >> sick))
        if n_good > 16:
            assert use == (2 >> sick if pop & (2 >> sick) else 0), f'decision {i}: {m.trace[i]}'
            assert m.curs[i] == 1 - sick
        if n_good == len(good_rx):
            break                       # after its last line the other receiver is all there is
    assert n_good == len(good_rx)


def out_of_step_receivers_are_not_mixed(seed, **kw):
    """Two good receivers out of step (B late by a fraction of a line, by whole lines, or
    both; B also numbers one field far too high). The output is A's lines, every one of them
    and nothing else: the current channel never changes, although each receiver is silent
    for a blanking interval while the other delivers. A's isolated bad lines have no partner
    and are left out (the field store covers them)."""
    rng = random.Random(seed)
    lost_a, lost_b = set(spots(rng, 8)), set(spots(rng, 8))
    bad_a = set(spots(rng, 4)) - lost_a
    ra = receiver(rng, 0.0, fields=FIELDS + 1, lost=lost_a, bad=bad_a)
    rb = receiver(rng, out_of_step(rng), lost=lost_b, shift={rng.randrange(FIELDS): 64})
    m = run(ra, rb, **kw)
    assert set(m.curs) == {0}
    assert all(use == (ref.USE_A if pop == 0b01 and not o else 0) for (use, pop, *_), o in zip(m.trace, m.omitted))
    assert out_fields(m.trace) == [[n for n in range(LINES) if (f, n) not in lost_a | bad_a] for f in range(FIELDS + 1)]


def field_starts_are_bounded(seed, **kw):
    """Anything goes: random offset, heavy loss, bad lines, wrong numbers, a decoder that
    reports no lock for a while. The output never has more field starts than the field
    starts of the receivers and the take-overs between them can account for (the old mixer
    made 160 fields out of 3 when one receiver lagged), and take-overs outside paired lines
    are at least eight lines apart."""
    rng = random.Random(seed)

    def damage(p):
        return {(f, n) for f in range(FIELDS) for n in range(LINES) if rng.random() < p}
    t_on = rng.uniform(0, FIELDS * FIELD_NS)
    ra = receiver(rng, 0.0, lost=damage(rng.choice((0, 0.05, 0.3))), bad=damage(rng.choice((0, 0.1))),
                  shift={rng.randrange(FIELDS): rng.randrange(1, 30)})
    rb = receiver(rng, rng.choice((rng.uniform(-5000, 5000), rng.uniform(0, 30) * LINE_NS)),
                  lost=damage(rng.choice((0, 0.05, 0.3))), bad=damage(rng.choice((0, 0.1))))
    m = run(ra, rb, ext_bad=(lambda t: t_on <= t < t_on + FIELD_NS, False), **kw)
    lone = [i for i in range(1, len(m.curs)) if m.curs[i] != m.curs[i - 1] and m.trace[i][1] != 0b11]
    assert len(out_fields(m.trace)) <= 1 + 2 * (2 * FIELDS) + len(lone)
    assert all(y - x >= 8 for x, y in zip(lone, lone[1:])), 'the current channel must not flap'


BOTH_BAD = [('', 'ab'), ('a', 'b'), ('b', 'a')]            # (lost on, bad on): no good copy anywhere


def lone_lines_bad_on_both_are_left_out(seed, **kw):
    """Receivers in step; runs of one to three lines without a good copy (bad on both, or lost on
    one and bad on the other), also at the first and last line of a field, next to isolated
    damage on one receiver. A line is left out only if it has no good copy, never two in a row
    within an output field, and exactly when the line shown before it in that field had a good
    copy (or it is the first line shown in the field). Every other line is shown as before."""
    rng = random.Random(seed)
    lost, bad = (set(), set()), (set(), set())
    taken = set()
    for _ in range(12):
        fld = rng.randrange(FIELDS)
        start = rng.choice((0, LINES - 1, rng.randrange(1, LINES - 1)))
        run_lines = [(fld, n) for n in range(start, min(start + rng.choice((1, 1, 2, 3)), LINES))]
        if any((f, n + d) in taken for f, n in run_lines for d in (-1, 0, 1)):
            continue
        for place in run_lines:
            lost_on, bad_on = rng.choice(BOTH_BAD)
            for ch, name in enumerate('ab'):
                if name in lost_on:
                    lost[ch].add(place)
                if name in bad_on:
                    bad[ch].add(place)
            taken.add(place)
    for place in spots(rng, 6):                                  # isolated damage on one receiver
        if not any((place[0], place[1] + d) in taken for d in (-1, 0, 1)):
            ch = rng.randrange(2)
            (lost if rng.randrange(2) else bad)[ch].add(place)
            taken.add(place)
    ra = receiver(rng, 0.0, lost=lost[0], bad=bad[0])
    rb = receiver(rng, rng.uniform(-5000, 5000), lost=lost[1], bad=bad[1])
    m, before = run(ra, rb, **kw), run(ra, rb, omit_bad=False)
    # everything but the use of left-out lines is decided as before
    assert m.curs == before.curs and [t[1:] for t in m.trace] == [t[1:] for t in before.trace]
    assert all(t == b or (o and b[0]) for t, b, o in zip(m.trace, before.trace, m.omitted)), 'only shown lines are left out'

    def no_good_copy(p):
        return all(p in lost[ch] or p in bad[ch] for ch in (0, 1))
    n_omitted, fld, prev, prev_shown, prev_omitted = 0, 0, -1, None, False
    for (use, _, _, line), (use_before, *_), omitted in zip(m.trace, before.trace, m.omitted):
        fld += line < prev
        prev = line
        if not use_before:
            continue                                             # not shown before either
        both = no_good_copy((fld, line))
        first = prev_shown is None or prev_shown[0] != fld
        want = both and (first or not no_good_copy(prev_shown))
        assert omitted == want, f'field {fld} line {line}: omitted {omitted}, expected {want}'
        assert not omitted or first or not prev_omitted, f'field {fld} line {line}: two left out in a row'
        prev_shown, prev_omitted = (fld, line), omitted
        n_omitted += omitted
    assert n_omitted, 'scenario without a line to leave out'


PROPERTIES = [in_step_every_good_line_is_shown_once, burst_loss_on_one_receiver_loses_nothing,
              unlocked_receiver_is_not_shown, out_of_step_receivers_are_not_mixed, field_starts_are_bounded,
              lone_lines_bad_on_both_are_left_out]


@pytest.mark.parametrize('seed', SEEDS)
@pytest.mark.parametrize('prop', PROPERTIES, ids=lambda p: p.__name__)
def test_mixer(prop, seed):
    prop(seed)


@pytest.mark.parametrize('prop, kw', [(in_step_every_good_line_is_shown_once, {'n_step': 0}),
                                      (burst_loss_on_one_receiver_loses_nothing, {'n_step': 0}),
                                      (unlocked_receiver_is_not_shown, {'n_dead': 8}),
                                      (out_of_step_receivers_are_not_mixed, {'n_dead': 16}),
                                      (lone_lines_bad_on_both_are_left_out, {'omit_bad': False})],
                         ids=lambda v: v.__name__ if callable(v) else '_'.join(f'{k}{x}' for k, x in v.items()))
def test_mixer_needs_its_rules(prop, kw):
    """Negative controls: without gap filling (N_STEP = 0), or with N_DEAD shorter than a
    blanking interval, the properties above fail (not for every seed: an unlocked receiver
    that happens to run in step never gets the chance to take over)."""
    failed = 0
    for seed in SEEDS:
        try:
            prop(seed, **kw)
        except AssertionError:
            failed += 1
    print(f'{failed} of {len(SEEDS)} runs failed')
    assert failed >= len(SEEDS) // 4, f'only {failed} of {len(SEEDS)} runs failed'
