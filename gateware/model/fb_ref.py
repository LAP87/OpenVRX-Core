"""Reference for the field store and the display mapping:
rtl/field_phase.v, rtl/fb_sdram.v (which buffer a frame shows, where each line
is read from, which buffer is written next) and rtl/fb_display.v (which source
line an output line shows).

The store is modelled at the level of its decisions. Feed it the events of the
SDRAM clock domain in the order they happen:
    first_word(f, line)   the first word of a field is at the head of the FIFO
    end_joined(f, line)   the field joined after reset ends and is dropped
    word(f, line, idx, t) a word is taken (t in cycles)
    line_stored(line)     the last group of a line has been written
    frame_start()         first line request of an output frame
    fetch(line)           a line request; returns (buffer, line) to read
sim/test_fb.py replays the events of a simulation and compares every decision.
"""
N_BUF = 4


def src_line(j, lines, v_active, low=False):
    """Source line shown on output line j: the centre of the output line, a quarter of a
    source line up (three quarters for the lower field of an interlaced pair)."""
    a = (2 * j + 1) * 2 * lines - (3 if low else 1) * v_active
    return max(0, min(lines - 1, a // (4 * v_active)))


class FieldPhase:
    """rtl/field_phase.v: which field of an interlaced pair, from arrival times (cycles)."""

    def __init__(self, t_eq=1024, t_max=6144, width=21):
        self.t_eq, self.t_max, self.sat = t_eq, t_max, (1 << width) - 1
        self.t_ref = None           # time of the last reference line
        self.d2 = None              # the interval before it
        self.low = self.il = False
        self.dly_s = 0

    def new_field(self):
        self.low = (not self.low) if self.il else False

    def ref(self, t):
        """Reference line at cycle t. Returns (early, delay): this field came after the
        shorter interval, and the delay a genlocked output gives its frame start."""
        cnt = self.sat if self.t_ref is None else min(t - self.t_ref, self.sat)
        usable = self.d2 is not None and cnt != self.sat
        diff = abs(cnt - self.d2) if usable else 0
        equal = usable and diff < self.t_eq
        step = usable and 2 * self.t_eq < diff < self.t_max
        longer = usable and cnt > self.d2
        half = diff >> 1
        early = False if equal else (not longer) if step else (self.il and not self.low)
        dly = half if (step and not self.il) else self.dly_s
        if equal:
            self.il = self.low = False
        elif step:
            self.dly_s = self.dly_s - (self.dly_s >> 2) + (half >> 2) if self.il else half
            self.il, self.low = True, longer
        self.t_ref, self.d2 = t, (None if cnt == self.sat else cnt)
        return early, dly


class FieldStore:
    """rtl/fb_sdram.v."""

    def __init__(self, rt_en=True, rt_ntsc=4, rt_pal=44, rt_hyst=16, rt_split=270, ref_line=1):
        self.rt_en, self.rt_ntsc, self.rt_pal, self.rt_hyst, self.rt_split = rt_en, rt_ntsc, rt_pal, rt_hyst, rt_split
        self.ref_line = ref_line
        self.cur = 0
        self.have_field = False
        self.joined = False                       # the current field is the one joined after reset
        self.cur_f = 0
        self.last_line = self.max_line = 0
        self.done_any, self.max_done = False, 0
        self.latest, self.latest_v = 0, False     # published buffers, newest first
        self.older, self.older_v = 0, False
        self.low_of = [False] * N_BUF
        self.ok = [set() for _ in range(N_BUF)]   # lines stored, per buffer
        self.n1 = None
        self.lines = 0                            # line count the display scales by (0: none yet)
        self.show, self.prev, self.prev_ok, self.rt_prev = 0, 0, False, False
        self.frame_low = False
        self.rep, self.miss = None, 0
        self.phase = FieldPhase()
        self.published = []                       # (buffer, line count of that field)

    # ---- writer
    def is_new_field(self, f, line):
        return self.have_field and (f != self.cur_f or line < self.last_line)

    def first_word(self, f, line):
        """The first word of a field is seen (before it is taken). Returns the buffer it will be written to."""
        if not self.have_field:
            self.have_field, self.cur_f, self.joined = True, f, True
        else:
            assert self.is_new_field(f, line) and not self.joined
            n = (self.max_line + 1) & 1023
            if self.n1 is None:
                self.lines = n
            elif abs(n - self.n1) <= 2:
                self.lines = min(n, self.n1)
            self.n1 = n
            self.published.append((self.cur, n))
            nxt = next(b for b in range(N_BUF) if b not in (self.cur, self.show, self.prev))
            self.older, self.older_v = self.latest, self.latest_v and nxt != self.latest
            self.latest, self.latest_v = self.cur, True
            self.low_of[self.cur] = self.phase.low
            self.cur, self.cur_f = nxt, f
            self.last_line = self.max_line = 0
            self.done_any, self.max_done = False, 0
        self.ok[self.cur] = set()
        self.phase.new_field()
        return self.cur

    def end_joined(self, f, line):
        """The field the writer joined ends: it is dropped, not published; the writer moves to a free buffer."""
        assert self.joined and self.is_new_field(f, line)
        nxt = next(b for b in range(N_BUF) if b not in (self.cur, self.show, self.prev))
        self.joined, self.cur, self.cur_f = False, nxt, f
        self.last_line = self.max_line = 0
        self.done_any, self.max_done = False, 0
        self.ok[self.cur] = set()
        self.phase.new_field()
        return self.cur

    def word(self, f, line, idx=None, t=None):
        assert self.have_field and not self.is_new_field(f, line)
        self.last_line = line
        self.max_line = max(self.max_line, line)
        if line == self.ref_line and idx == 0:
            self.phase.ref(t)

    def line_stored(self, line):
        self.ok[self.cur].add(line)
        self.done_any, self.max_done = True, line

    # ---- display
    def frame_start(self):
        """Returns (shown buffer, fallback buffer or None, lower field, shows the field being written)."""
        thr = self.rt_pal if self.lines > self.rt_split else self.rt_ntsc
        if not self.rt_prev:
            thr += self.rt_hyst
        rt = bool(self.rt_en and self.have_field and self.done_any and self.max_done + 1 >= thr)
        if rt or not self.latest_v:
            self.show, self.frame_low = self.cur, self.phase.low
        else:
            self.show, self.frame_low = self.latest, self.low_of[self.latest]
        if rt:
            self.prev, self.prev_ok = self.latest, self.latest_v
        else:
            self.prev, self.prev_ok = self.older, self.latest_v and self.older_v
        self.rt_prev = rt
        self.rep, self.miss = None, 0
        return self.show, (self.prev if self.prev_ok else None), self.frame_low, rt

    def fetch(self, line):
        """Where line `line` of this frame is read from: (buffer, line)."""
        if line in self.ok[self.show]:
            src, self.miss = (self.show, line), 0
            self.rep = src
        else:
            miss, self.miss = self.miss, min(self.miss + 1, 3)
            if self.rep is not None and miss < 2:
                src = self.rep                                   # the line above
            elif self.prev_ok and line in self.ok[self.prev]:
                src = self.rep = (self.prev, line)
            elif self.rep is not None:
                src = self.rep
            else:
                src = self.rep = (self.show, line)
        return src
