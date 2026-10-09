"""Independent model for the shared LOW/BUF line-buffer RAM.

Initialization is deliberately distinct from the RAM contents: an unwritten
slot reads as BLACK in LOW mode, while a slot written before remains readable
when a later line is absent. The address tracker accepts only a contiguous
physical run of words 0..359 in one slot.
"""

from bisect import bisect_left

BLACK_WORD = 0x10801080
SLOT_WORDS = 512
LINE_WORDS = 360
SLOT_COUNT = 16
DEPTH = SLOT_WORDS * SLOT_COUNT


class LineBuffer:
    def __init__(self):
        self.words = {}
        self.samples = [[] for _ in range(SLOT_COUNT)]
        self.reset()

    def reset(self):
        # The physical dual-clock RAM has no reset. Only sticky initialization
        # state and in-flight coverage clear; the old data remains in memory.
        self.initialized = 0
        self.completions = [[] for _ in range(SLOT_COUNT)]
        self._candidate_addresses = []

    def accept_write(self, address, data, time_ns=None):
        """Apply one accepted physical write and advance contiguous coverage."""
        if not 0 <= address < DEPTH:
            raise ValueError(f"line-buffer address {address} is out of range")
        if data is not None and not 0 <= data <= 0xFFFFFFFF:
            raise ValueError(f"line-buffer word {data} is not 32-bit")
        slot, index = divmod(address, SLOT_WORDS)
        if data is not None:
            self.words[address] = data
            if index == 52 and time_ns is not None:
                self.samples[slot].append((time_ns, data, None))

        if index == 0:
            self._candidate_addresses = [address]
        elif self._candidate_addresses:
            previous = self._candidate_addresses[-1]
            if previous // SLOT_WORDS == slot and address == previous + 1:
                self._candidate_addresses.append(address)
            else:
                self._candidate_addresses = []

        if index == LINE_WORDS - 1:
            expected = tuple(range(slot * SLOT_WORDS, slot * SLOT_WORDS + LINE_WORDS))
            if tuple(self._candidate_addresses) == expected:
                self.initialized |= 1 << slot
                if time_ns is not None:
                    self.completions[slot].append(time_ns)
            self._candidate_addresses = []

    def accept_range(self, first_address, last_address, time_ns=None):
        """Replay a logged maximal consecutive accepted-address run."""
        if last_address < first_address:
            raise ValueError("accepted-address run ends before it starts")
        for address in range(first_address, last_address + 1):
            self.accept_write(address, None, time_ns if address == last_address else None)

    def record_sample(self, address, data, time_ns, provenance=None):
        """Record word 52 from a compact trace without advancing coverage twice."""
        if not 0 <= address < DEPTH or address % SLOT_WORDS != 52:
            raise ValueError(f"sample address {address} is not a line-buffer word 52")
        if not 0 <= data <= 0xFFFFFFFF:
            raise ValueError(f"line-buffer word {data} is not 32-bit")
        slot = address // SLOT_WORDS
        self.words[address] = data
        self.samples[slot].append((time_ns, data, provenance))

    def valid_at(self, slot, time_ns=None):
        if not 0 <= slot < SLOT_COUNT:
            raise ValueError(f"line-buffer slot {slot} is out of range")
        if time_ns is None:
            return bool(self.initialized & (1 << slot))
        return any(t is not None and t < time_ns for t in self.completions[slot])

    def sample_at(self, slot, index, time_ns):
        """Latest recorded word at an address strictly before `time_ns`."""
        event = self.sample_event_at(slot, index, time_ns)
        return event[1] if event is not None else None

    def sample_event_at(self, slot, index, time_ns):
        """Latest `(time, word, provenance)` event strictly before `time_ns`."""
        address = slot * SLOT_WORDS + index
        if not 0 <= address < DEPTH:
            raise ValueError(f"line-buffer slot/index {(slot, index)} is out of range")
        history = self.samples[slot] if index == 52 else None
        if history is not None:
            i = bisect_left([t for t, _, _ in history], time_ns)
            return history[i - 1] if i else None
        value = self.words.get(address)
        return (None, value, None) if value is not None else None

    def expected(self, slot, index, *, read_time_ns, valid_time_ns, low=True):
        """Value presented to the display for a registered RAM read.

        `valid_time_ns` is the pixel edge at which the first synchronizer
        stage samples the sticky write-domain bit. The value consumed by the
        display uses the second-stage value from that edge and the RAM result
        registered one pixel edge earlier, so callers supply those two
        observation times explicitly.
        """
        if low and not self.valid_at(slot, valid_time_ns):
            return BLACK_WORD
        return self.sample_at(slot, index, read_time_ns)


class PixelReadPipeline:
    """Clock-edge model of the two-flop mask sync and one-cycle RAM read.

    `posedge` first returns the old, post-read value consumed by the display,
    then models nonblocking updates for this edge. Callers apply accepted
    writes between pixel edges; simultaneous write/read edges therefore see
    the pre-edge memory value, as the synchronous RAM does.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.sync1 = 0
        self.sync2 = 0
        self.address_q = None
        self.low_q = False
        self.data_q = None

    def display_input(self, linebuf):
        """Current combinational masked RAM value presented to fb_display."""
        if self.address_q is None:
            return None
        if self.low_q and not (self.sync2 >> (self.address_q // SLOT_WORDS) & 1):
            return BLACK_WORD
        return self.data_q

    def posedge(self, linebuf, requested_address, low):
        consumed = self.display_input(linebuf)

        old_sync1 = self.sync1
        self.sync1 = linebuf.initialized
        self.sync2 = old_sync1
        self.address_q = requested_address
        self.low_q = bool(low)
        self.data_q = linebuf.words.get(requested_address)
        return consumed
