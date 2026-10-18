"""Reference for rtl/chan_scan.v: which channel a scan keeps.

obs[i] = (ok_a, noise_a, ok_b, noise_b) for channel i = band * 8 + channel: whether receiver
A / B counted on that channel (its second noise window after the settling came, and its
decoder was locked when the channel was decided) and that window's noise value. observe()
works the observations out from a scan's events.
A channel's score is the lower noise of the counting receivers; the lowest score wins, the
earlier channel on a tie. No counting receiver on any channel: the scan keeps the starting
channel (found False). An abort keeps the starting channel.
"""


def score(o):
    ok_a, na, ok_b, nb = o
    vals = [v for ok, v in ((ok_a, na), (ok_b, nb)) if ok]
    return min(vals) if vals else None


def scan(obs, start_idx):
    """(channel kept, found)."""
    best = None
    for i, o in enumerate(obs):
        s = score(o)
        # the starting channel keeps a tie (Core #22); otherwise the earlier channel
        if s is not None and (best is None or s < best[0] or (s == best[0] and i == start_idx)):
            best = (s, i)
    return (best[1], True) if best else (start_idx, False)


def observe(tunes, windows, decided_at, locks, lock_ms, settle_ms=30, max_ms=200):
    """Observations from a scan's events. tunes: [(idx, t_us)] in order; windows: {'A': [(t_us, v)],
    'B': [...]}; decided_at[i]: when channel i was decided (the next tune, or the end); locks[i] =
    (world lock A, world lock B). A window counts if it ends after the settling; the second one
    is taken if it ends within max_ms of the settling."""
    obs = []
    for k, (i, t0) in enumerate(tunes):
        s = t0 + settle_ms * 1000
        o = []
        for ch, wl in enumerate(('A', 'B')):
            after = [(t, v) for t, v in windows[wl] if t > s]
            second = after[1] if len(after) >= 2 and after[1][0] <= s + max_ms * 1000 else None
            locked = locks[i][ch] and decided_at[k] - t0 >= lock_ms * 1000
            o += [second is not None and locked, second[1] if second else 0]
        obs.append(tuple(o))
    return obs
