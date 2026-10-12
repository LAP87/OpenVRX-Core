"""tvp_ctrl (I2C bring-up, status polling and re-initialisation of our own
TVP5150AM1s) against behavioural I2C slaves.

Start-up: RESETB pulse, six register writes per decoder in a fixed order (03h last), status
from 88h/89h. Afterwards 03h is read back in every poll round: a decoder whose
registers are back at their defaults gets the list again, and that is counted.
Controls: an undisturbed run counts nothing and writes nothing more; a decoder
that ignores writes, or an SDA line shorted low, makes the counter stop at 255
instead of wrapping; a decoder that joins late is brought up, and the error
flag follows it on and off the bus.

Run: .venv/bin/python -m pytest -q gateware/sim/test_tvp_ctrl.py"""
import hashlib
import math
import os
import re
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(HERE))
import tvp_status  # noqa: E402

# Independent physical-pin I2C edge decoder used only by controller tests.

# Input records are ``(timestamp, SCL, SDA0, SDA1)`` snapshots of resolved pins.
# The decoder deliberately has no connection to the controller or slave model.


class TraceError(ValueError):
    """The sampled pin trace is invalid, incomplete, or outside the supported shape."""


@dataclass(frozen=True)
class AckSample:
    """One ninth-clock sample. ``acknowledged`` is the electrical low level."""

    phase: str  # address, register, or data
    direction: str  # write or read
    acknowledged: bool
    actor: str  # device or master


@dataclass(frozen=True)
class Transaction:
    """One STOP-terminated register access observed on the resolved pins."""

    device: int  # split-SDA lane, or shared-bus address slot (0=5Ch, 1=5Dh)
    address: int
    direction: str  # write or read
    register: int | None
    data: tuple[int, ...]
    acks: tuple[AckSample, ...]
    started_at: int | float
    repeated_start_at: int | float | None
    stopped_at: int | float
    aborted: bool


@dataclass(frozen=True)
class _WireByte:
    value: int
    acknowledged: bool
    segment: int


class _ActiveTransfer:
    def __init__(self, lane: int, started_at: int | float):
        self.lane = lane
        self.started_at = started_at
        self.restarts: list[int | float] = []
        self.segment = 0
        self.bytes: list[_WireByte] = []
        self.value = 0
        self.bit_count = 0
        self.pending_rise_sda: int | None = None

    def clock_rising(self, sda: int) -> None:
        if self.bit_count < 8:
            self.value = (self.value << 1) | sda
            self.bit_count += 1
            return
        self.bytes.append(_WireByte(self.value, sda == 0, self.segment))
        self.value = 0
        self.bit_count = 0

    def repeated_start(self, timestamp: int | float) -> None:
        # The SCL rise immediately before a repeated START is a high-phase
        # setup edge, not a data clock. SDA falling while SCL stays high tells
        # us to discard that pending edge.
        self.pending_rise_sda = None
        self._require_byte_boundary("repeated START")
        if self.restarts:
            raise TraceError("more than one repeated START is unsupported")
        self.restarts.append(timestamp)
        self.segment += 1

    def stop(self, timestamp: int | float, topology: str) -> Transaction:
        # As above, a STOP's SCL rise is followed by SDA rising while SCL is
        # still high; that pair is the stop condition, not a new data bit.
        self.pending_rise_sda = None
        self._require_byte_boundary("STOP")
        return _make_transaction(self, timestamp, topology)

    def commit_pending_rise(self) -> None:
        if self.pending_rise_sda is not None:
            self.clock_rising(self.pending_rise_sda)
            self.pending_rise_sda = None

    def _require_byte_boundary(self, marker: str) -> None:
        if self.bit_count:
            raise TraceError(f"incomplete byte before {marker} at time {self.started_at}")


def decode_i2c_pin_trace(
    events: Iterable[tuple[int | float, int, int, int]],
    topology: str = "shared_sda",
) -> tuple[Transaction, ...]:
    """Decode STOP-terminated register accesses from resolved pin snapshots.

    ``topology`` is ``"shared_sda"`` for one physical SDA mirrored in both
    columns and addresses 5Ch/5Dh, or ``"split_sda"`` for two SDA lanes at
    address 5Ch. Split mode chooses a device from the lane that asserted START;
    it never decodes the inactive lane during that transfer.

    The initial record must be fully idle high on SCL, SDA0, and SDA1, so a
    trace cropped from an in-progress transfer cannot look like an empty bus.
    Events with equal timestamps retain input order. A rising SCL with a candidate or
    active-lane SDA change in the same record is rejected because the sampled
    order is ambiguous. An SDA change coincident with falling SCL is accepted
    as a settled data change.
    """

    if topology not in ("shared_sda", "split_sda"):
        raise TraceError("topology must be 'shared_sda' or 'split_sda'")

    iterator = iter(events)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise TraceError("empty pin trace; an initial baseline is required") from exc

    previous = _validate_event(first, 0, None)
    if previous[1:] != (1, 1, 1):
        raise TraceError("initial baseline must be idle high on SCL, SDA0, and SDA1")
    if topology == "shared_sda" and previous[2] != previous[3]:
        raise TraceError("shared_sda baseline has different SDA0 and SDA1 levels")

    active: _ActiveTransfer | None = None
    transactions: list[Transaction] = []
    previous_time = previous[0]

    for index, raw_event in enumerate(iterator, start=1):
        current = _validate_event(raw_event, index, previous_time)
        timestamp, scl, sda0, sda1 = current
        _old_time, old_scl, old_sda0, old_sda1 = previous
        if topology == "shared_sda" and sda0 != sda1:
            raise TraceError(f"shared_sda event {index} has different SDA0 and SDA1 levels")

        old_sdas = (old_sda0, old_sda1)
        sdas = (sda0, sda1)
        lanes = (0,) if topology == "shared_sda" else (0, 1)
        changed = [lane for lane in lanes if old_sdas[lane] != sdas[lane]]
        scl_rose = old_scl == 0 and scl == 1
        scl_fell = old_scl == 1 and scl == 0

        if scl_rose and (
            (active is None and changed)
            or (active is not None and active.lane in changed)
        ):
            raise TraceError(f"ambiguous simultaneous SCL rise and SDA change at time {timestamp}")

        if active is None and scl_fell and any(
            old_sdas[lane] == 1 and sdas[lane] == 0 for lane in changed
        ):
            raise TraceError(f"ambiguous simultaneous SCL fall and idle SDA fall at time {timestamp}")

        # START/STOP require SCL to be high both before and after the SDA edge.
        stable_high = old_scl == 1 and scl == 1
        delimiters: list[tuple[int, str]] = []
        if stable_high:
            for lane in changed:
                edge = "start" if old_sdas[lane] == 1 and sdas[lane] == 0 else "stop"
                delimiters.append((lane, edge))

        if active is None:
            starts = [lane for lane, edge in delimiters if edge == "start"]
            if len(starts) > 1:
                raise TraceError(f"both split SDA lanes asserted START at time {timestamp}")
            if starts:
                active = _ActiveTransfer(starts[0], timestamp)
        else:
            active_delimiters = [edge for lane, edge in delimiters if lane == active.lane]
            other_delimiters = [lane for lane, _edge in delimiters if lane != active.lane]
            other_starts = [
                lane for lane, edge in delimiters if lane != active.lane and edge == "start"
            ]
            if other_starts:
                raise TraceError(f"overlapping split-SDA START on inactive lane at time {timestamp}")
            if active_delimiters and other_delimiters:
                raise TraceError(f"overlapping split-SDA edges at time {timestamp}")
            if len(active_delimiters) > 1:
                raise TraceError(f"ambiguous SDA edge at time {timestamp}")
            if active_delimiters:
                if active_delimiters[0] == "start":
                    active.repeated_start(timestamp)
                else:
                    transactions.append(active.stop(timestamp, topology))
                    active = None

        if active is not None and scl_fell:
            # Defer a rising-edge sample until the following falling edge. A
            # stable-high SDA transition in between identifies START or STOP,
            # whose preceding SCL rise is not a data clock.
            active.commit_pending_rise()
        elif active is not None and scl_rose:
            active.pending_rise_sda = sdas[active.lane]

        previous = current
        previous_time = timestamp

    if active is not None:
        if active.pending_rise_sda is not None:
            raise TraceError(
                f"unfinished SCL high phase at EOF in transaction started at {active.started_at}"
            )
        if active.bit_count:
            raise TraceError(f"incomplete byte at EOF in transaction started at {active.started_at}")
        raise TraceError(f"transaction started at {active.started_at} has no STOP at EOF")
    return tuple(transactions)


def _validate_event(
    event: tuple[int | float, int, int, int], index: int, previous_time: int | float | None
) -> tuple[int | float, int, int, int]:
    if not isinstance(event, (tuple, list)) or len(event) != 4:
        raise TraceError(f"event {index} must contain timestamp, SCL, SDA0, SDA1")
    timestamp, scl, sda0, sda1 = event
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise TraceError(f"event {index} has an invalid timestamp")
    if isinstance(timestamp, float) and not math.isfinite(timestamp):
        raise TraceError(f"event {index} has a non-finite timestamp")
    if previous_time is not None and timestamp < previous_time:
        raise TraceError(f"time moved backwards at event {index}: {timestamp} < {previous_time}")
    pins = (scl, sda0, sda1)
    labels = ("SCL", "SDA0", "SDA1")
    normalized: list[int] = []
    for label, value in zip(labels, pins):
        if isinstance(value, bool):
            normalized.append(int(value))
        elif type(value) is int and value in (0, 1):
            normalized.append(value)
        else:
            raise TraceError(f"unknown {label} pin value at event {index}: {value!r}")
    return timestamp, normalized[0], normalized[1], normalized[2]


def _make_transaction(
    transfer: _ActiveTransfer, stopped_at: int | float, topology: str
) -> Transaction:
    segments: dict[int, list[_WireByte]] = {}
    for wire_byte in transfer.bytes:
        segments.setdefault(wire_byte.segment, []).append(wire_byte)
    first = segments.get(0, [])
    if not first:
        raise TraceError(f"STOP at {stopped_at} before a complete address byte")

    first_address = first[0].value >> 1
    first_read = bool(first[0].value & 1)
    if topology == "split_sda":
        if first_address != 0x5C:
            raise TraceError(f"split_sda supports only address 5Ch, saw {first_address:02X}h")
        device = transfer.lane
    else:
        if first_address not in (0x5C, 0x5D):
            raise TraceError(
                f"shared_sda supports only addresses 5Ch and 5Dh, saw {first_address:02X}h"
            )
        device = first_address - 0x5C

    acks: list[AckSample] = []
    register: int | None = None
    data: tuple[int, ...] = ()
    aborted = False

    if transfer.restarts:
        second = segments.get(1, [])
        if set(segments) != {0, 1} or len(first) != 2 or len(second) != 2:
            raise TraceError("repeated START requires address-W, register, address-R, one data byte")
        if first_read or not (second[0].value & 1):
            raise TraceError("repeated START shape must be a write-register followed by a read")
        if second[0].value >> 1 != first_address:
            raise TraceError("repeated read address differs from the initial address")
        register = first[1].value
        data = (second[1].value,)
        acks.extend(
            (
                AckSample("address", "write", first[0].acknowledged, "device"),
                AckSample("register", "write", first[1].acknowledged, "device"),
                AckSample("address", "read", second[0].acknowledged, "device"),
                AckSample("data", "read", second[1].acknowledged, "master"),
            )
        )
        direction = "read"
    else:
        if set(segments) != {0}:
            raise TraceError("unsupported transfer segment shape")
        direction = "read" if first_read else "write"
        acks.append(AckSample("address", direction, first[0].acknowledged, "device"))
        if len(first) == 1:
            aborted = True
            if first[0].acknowledged:
                # A STOP immediately after an ACKed address is still useful
                # evidence of an abort, and carries the observed address ACK.
                pass
        elif direction == "write" and len(first) == 2:
            register = first[1].value
            acks.append(AckSample("register", "write", first[1].acknowledged, "device"))
            aborted = True
        elif direction == "write" and len(first) == 3:
            register = first[1].value
            data = (first[2].value,)
            acks.extend(
                (
                    AckSample("register", "write", first[1].acknowledged, "device"),
                    AckSample("data", "write", first[2].acknowledged, "device"),
                )
            )
        else:
            raise TraceError("unsupported shape; expected one-byte register write or combined read")

    return Transaction(
        device=device,
        address=first_address,
        direction=direction,
        register=register,
        data=data,
        acks=tuple(acks),
        started_at=transfer.started_at,
        repeated_start_at=transfer.restarts[0] if transfer.restarts else None,
        stopped_at=stopped_at,
        aborted=aborted,
    )


# Pure pin-level fixtures for the independent I2C edge decoder.


# Frozen db0035f tvp_ctrl.v init_rom(), with VIDEO_STD=00h and OP_MODE=30h.
INIT_WRITES = (
    (0x00, 0x00),
    (0x04, 0xFC),
    (0x0D, 0x47),
    (0x28, 0x00),
    (0x02, 0x30),
    (0x03, 0x0D),
)


class BusFixture:
    """Build resolved SCL/SDA edges without consulting decoder output."""

    def __init__(self, shared=True):
        self.shared = shared
        self.time = 0
        self.levels = [1, 1, 1]
        self.events = [(self.time, *self.levels)]

    def _set(self, *, scl=None, sda0=None, sda1=None):
        updates = (scl, sda0, sda1)
        changed = False
        for index, value in enumerate(updates):
            if value is not None and value != self.levels[index]:
                self.levels[index] = value
                changed = True
        if changed:
            self.time += 1
            self.events.append((self.time, *self.levels))
        return self.time

    def _set_sda(self, lane, value):
        if self.shared:
            return self._set(sda0=value, sda1=value)
        return self._set(**{f"sda{lane}": value})

    def _set_bit_clock(self, lane, bit):
        if self.shared:
            return self._set(scl=0, sda0=bit, sda1=bit)
        return self._set(scl=0, **{f"sda{lane}": bit})

    def start(self, lane):
        return self._set_sda(lane, 0)

    def repeated_start(self, lane):
        self._set_sda(lane, 1)
        self._set(scl=1)
        at = self._set_sda(lane, 0)
        self._set(scl=0)
        return at

    def byte(self, lane, value, ninth_high=False):
        """Clock one byte MSB first, then the physical ninth-bit level."""
        for shift in range(7, -1, -1):
            bit = (value >> shift) & 1
            # On the first bit, falling SCL and the data change may settle in
            # the same physical sample. The decoder must defer sampling until
            # the following SCL rise.
            self._set_bit_clock(lane, bit)
            self._set(scl=1)
            self._set(scl=0)
        self._set_sda(lane, int(ninth_high))
        self._set(scl=1)
        self._set(scl=0)

    def write(self, lane, address, register, data, *, ack_address=True, ack_register=True, ack_data=True):
        started = self.start(lane)
        self.byte(lane, address << 1, ninth_high=not ack_address)
        self.byte(lane, register, ninth_high=not ack_register)
        self.byte(lane, data, ninth_high=not ack_data)
        self._set_sda(lane, 0)
        self._set(scl=1)
        stopped = self._set_sda(lane, 1)
        return started, stopped

    def stop_after_address(self, lane, address, *, ack_address):
        started = self.start(lane)
        self.byte(lane, address << 1, ninth_high=not ack_address)
        self._set_sda(lane, 0)
        self._set(scl=1)
        stopped = self._set_sda(lane, 1)
        return started, stopped

    def register_read(self, lane, address, register, value):
        started = self.start(lane)
        self.byte(lane, address << 1, ninth_high=False)
        self.byte(lane, register, ninth_high=False)
        repeated = self.repeated_start(lane)
        self.byte(lane, (address << 1) | 1, ninth_high=False)
        # The device puts this data byte on SDA. The master releases SDA for
        # the ninth clock, so the observed NACK is normal single-byte ending.
        self.byte(lane, value, ninth_high=True)
        self._set_sda(lane, 0)
        self._set(scl=1)
        stopped = self._set_sda(lane, 1)
        return started, repeated, stopped


def _write_expected(device, address, register, value, started, stopped):
    return Transaction(
        device=device,
        address=address,
        direction="write",
        register=register,
        data=(value,),
        acks=(
            AckSample("address", "write", True, "device"),
            AckSample("register", "write", True, "device"),
            AckSample("data", "write", True, "device"),
        ),
        started_at=started,
        repeated_start_at=None,
        stopped_at=stopped,
        aborted=False,
    )


class TestPinTraceFixtures(unittest.TestCase):
    def test_split_sda_same_address_captures_both_init_lists_once(self):
        bus = BusFixture(shared=False)
        bounds = []
        for lane in (0, 1):
            for register, value in INIT_WRITES:
                bounds.append(bus.write(lane, 0x5C, register, value))

        decoded = decode_i2c_pin_trace(bus.events, "split_sda")
        expected = []
        for lane in (0, 1):
            offset = lane * len(INIT_WRITES)
            for index, (register, value) in enumerate(INIT_WRITES):
                expected.append(
                    _write_expected(lane, 0x5C, register, value, *bounds[offset + index])
                )
        self.assertEqual(decoded, tuple(expected))
        self.assertEqual([transaction.device for transaction in decoded], [0] * 6 + [1] * 6)
        self.assertEqual([transaction.address for transaction in decoded], [0x5C] * 12)

    def test_shared_sda_selects_two_addresses_without_duplicate_lane_decode(self):
        bus = BusFixture(shared=True)
        expected = []
        for lane, address in ((0, 0x5C), (1, 0x5D)):
            for register, value in INIT_WRITES:
                started, stopped = bus.write(lane, address, register, value)
                expected.append(_write_expected(lane, address, register, value, started, stopped))

        decoded = decode_i2c_pin_trace(bus.events, "shared_sda")
        self.assertEqual(decoded, tuple(expected))
        self.assertEqual(len(decoded), 12)
        self.assertEqual([transaction.device for transaction in decoded], [0] * 6 + [1] * 6)

    def test_combined_repeated_start_read_records_master_nack_as_normal(self):
        bus = BusFixture(shared=True)
        started, repeated, stopped = bus.register_read(0, 0x5C, 0x03, 0x0D)
        expected = Transaction(
            device=0,
            address=0x5C,
            direction="read",
            register=0x03,
            data=(0x0D,),
            acks=(
                AckSample("address", "write", True, "device"),
                AckSample("register", "write", True, "device"),
                AckSample("address", "read", True, "device"),
                AckSample("data", "read", False, "master"),
            ),
            started_at=started,
            repeated_start_at=repeated,
            stopped_at=stopped,
            aborted=False,
        )
        self.assertEqual(decode_i2c_pin_trace(bus.events), (expected,))

    def test_address_register_and_data_nacks_remain_separate_and_observable(self):
        address_bus = BusFixture(shared=True)
        address_bounds = address_bus.stop_after_address(0, 0x5C, ack_address=False)
        address_expected = Transaction(
            0,
            0x5C,
            "write",
            None,
            (),
            (AckSample("address", "write", False, "device"),),
            address_bounds[0],
            None,
            address_bounds[1],
            True,
        )
        self.assertEqual(
            decode_i2c_pin_trace(address_bus.events), (address_expected,),
            "an address-NACK abort must produce an observable transaction",
        )

        continued = BusFixture(shared=True)
        started, stopped = continued.write(
            0, 0x5C, 0x02, 0x20, ack_address=False, ack_register=True, ack_data=True
        )
        continued_expected = Transaction(
            0,
            0x5C,
            "write",
            0x02,
            (0x20,),
            (
                AckSample("address", "write", False, "device"),
                AckSample("register", "write", True, "device"),
                AckSample("data", "write", True, "device"),
            ),
            started,
            None,
            stopped,
            False,
        )
        self.assertEqual(
            decode_i2c_pin_trace(continued.events),
            (continued_expected,),
            "a NACK does not erase the later bytes that were physically clocked",
        )

        for rejected_phase in ("register", "data"):
            with self.subTest(rejected_phase=rejected_phase):
                bus = BusFixture(shared=True)
                started, stopped = bus.write(
                    0,
                    0x5C,
                    0x02,
                    0x20,
                    ack_register=rejected_phase != "register",
                    ack_data=rejected_phase != "data",
                )
                ack_register = rejected_phase != "register"
                ack_data = rejected_phase != "data"
                expected = Transaction(
                    0,
                    0x5C,
                    "write",
                    0x02,
                    (0x20,),
                    (
                        AckSample("address", "write", True, "device"),
                        AckSample("register", "write", ack_register, "device"),
                        AckSample("data", "write", ack_data, "device"),
                    ),
                    started,
                    None,
                    stopped,
                    False,
                )
                self.assertEqual(decode_i2c_pin_trace(bus.events), (expected,))

    def test_wrong_register_and_value_are_visible_in_the_decoded_bus_result(self):
        bus = BusFixture(shared=True)
        bus.write(0, 0x5C, 0x03, 0x20)
        decoded = decode_i2c_pin_trace(bus.events)
        self.assertEqual((decoded[0].register, decoded[0].data), (0x03, (0x20,)))
        self.assertNotEqual((decoded[0].register, decoded[0].data), (0x02, (0x30,)))

    def test_inactive_split_lane_does_not_duplicate_or_steal_active_transaction(self):
        bus = BusFixture(shared=False)
        started = bus.start(1)
        bus.byte(1, 0xB8, ninth_high=False)
        # Lane 0 is inactive. Its low-clock transitions must not create a
        # second transaction while lane 1 owns this physical transfer.
        bus._set(sda0=0)
        bus._set(sda0=1)
        bus.byte(1, 0x28, ninth_high=False)
        bus.byte(1, 0x7A, ninth_high=False)
        bus._set_sda(1, 0)
        bus._set(scl=1)
        stopped = bus._set_sda(1, 1)

        decoded = decode_i2c_pin_trace(bus.events, "split_sda")
        self.assertEqual(
            decoded,
            (_write_expected(1, 0x5C, 0x28, 0x7A, started, stopped),),
        )

    def test_missing_stop_and_truncated_byte_fail_at_eof(self):
        no_stop = BusFixture()
        no_stop.start(0)
        no_stop.byte(0, 0xB8)
        no_stop.byte(0, 0x02)
        no_stop.byte(0, 0x30)
        with self.assertRaisesRegex(TraceError, "no STOP at EOF"):
            decode_i2c_pin_trace(no_stop.events)

        truncated = BusFixture(shared=True)
        truncated.start(0)
        for bit in (1, 0, 1, 1):
            truncated._set(scl=0, sda0=bit, sda1=bit)
            truncated._set(scl=1)
            truncated._set(scl=0)
        with self.assertRaisesRegex(TraceError, "incomplete byte at EOF"):
            decode_i2c_pin_trace(truncated.events)

    def test_unknown_pins_and_time_reversal_are_rejected(self):
        with self.assertRaisesRegex(TraceError, "unknown SDA0 pin value"):
            decode_i2c_pin_trace(((0, 1, 1, 1), (1, 1, "x", 1)))
        with self.assertRaisesRegex(TraceError, "time moved backwards"):
            decode_i2c_pin_trace(((2, 1, 1, 1), (1, 1, 1, 1)))
        with self.assertRaisesRegex(TraceError, "initial baseline must be idle high"):
            decode_i2c_pin_trace(((0, 1, 1, 0),), "split_sda")

    def test_inactive_lane_start_overlaps_and_rejects_active_split_transfer(self):
        bus = BusFixture(shared=False)
        bus.start(1)
        # Both lines are now at SCL high; a second lane START cannot be
        # assigned to an independent I2C transaction on the shared clock.
        bus._set(sda0=0)
        with self.assertRaisesRegex(TraceError, "overlapping split-SDA START"):
            decode_i2c_pin_trace(bus.events, "split_sda")

    def test_ambiguous_rising_edge_and_unsupported_multibyte_write_are_rejected(self):
        ambiguous = BusFixture(shared=True)
        ambiguous.start(0)
        ambiguous._set(scl=0)
        ambiguous._set(scl=1, sda0=1, sda1=1)
        with self.assertRaisesRegex(TraceError, "ambiguous simultaneous SCL rise"):
            decode_i2c_pin_trace(ambiguous.events)

        multi = BusFixture(shared=True)
        multi.start(0)
        multi.byte(0, 0xB8)
        multi.byte(0, 0x02)
        multi.byte(0, 0x30)
        multi.byte(0, 0x30)
        multi._set_sda(0, 0)
        multi._set(scl=1)
        multi._set_sda(0, 1)
        with self.assertRaisesRegex(TraceError, "unsupported shape"):
            decode_i2c_pin_trace(multi.events)


INIT = ('0d', 'fc', '47')           # 03h, 04h, 0Dh after the init list (00h = 00h is the default anyway)
SET = ('30', '00')                  # 02h (TV/VCR mode: TV), 28h (video standard: autoswitch, also the default)
INIT_LIST = [('00', '00'), ('04', 'fc'), ('0d', '47'), ('28', '00'), ('02', '30'), ('03', '0d')]
N = len(INIT_LIST)
ST_NTSC, ST_PAL = '000e', '306e'    # {89h, 88h} of the two decoder models: healthy NTSC and healthy PAL


def test_status_words_mean_what_the_datasheet_says():
    """The status words used by the models, the tests and BRINGUP.md, against the bit
    tables of SLES209E (sim/tvp_status.py)."""
    ntsc, pal = int(ST_NTSC, 16), int(ST_PAL, 16)
    assert tvp_status.healthy(ntsc, 'ntsc') and not tvp_status.healthy(ntsc, 'pal')
    assert tvp_status.healthy(pal, 'pal') and not tvp_status.healthy(pal, 'ntsc')
    # bits that vary on a good signal: field (89h bit 4), PAL switch (89h bit 5), peak white, VCR
    assert all(tvp_status.healthy(st, 'ntsc') for st in (0x000E, 0x100E, 0x008E, 0x000F))
    assert all(tvp_status.healthy(st, 'pal') for st in (0x006E, 0x106E, 0x206E, 0x306E))
    # negative controls: the words used here before. 402E is 50 Hz with the weak-signal flag,
    # 0006 is 60 Hz without colour lock; and no lock at all
    old = tvp_status.decode(0x402E)
    assert old['field_50hz'] and old['weak_signal'] and not old['line_alternating']
    assert not tvp_status.healthy(0x402E, 'ntsc') and not tvp_status.healthy(0x402E, 'pal')
    assert not tvp_status.healthy(0x0006, 'pal') and not tvp_status.healthy(0x0006, 'ntsc')
    assert not tvp_status.healthy(0x0000, 'ntsc')


KEEP_VALID = ("dev_err[di] <= 1'b1; status_valid[di] <= 1'b0; st <= S_NEXT;", "dev_err[di] <= 1'b1; st <= S_NEXT;")


BUS_TEXT_ROW = re.compile(r'^BUS ([0-9]+) ([01]) ([01]) ([01])$')


def parse_bus_text(output):
    """Strictly ingest every BUS-prefixed simulator line before pin decoding."""
    events = []
    for line in output.splitlines():
        if not line.startswith('BUS'):
            continue
        match = BUS_TEXT_ROW.fullmatch(line)
        if match is None:
            raise TraceError(f'malformed BUS text row: {line!r}')
        events.append(tuple(map(int, match.groups())))
    if not events:
        raise TraceError('empty BUS trace')
    return tuple(events)


def run(present1, split=0, scenario=0, alter=None, trace=0, tag=''):
    """Returns the testbench's RESULT line as a dict, and its MID line (or None).
    alter: (text, replacement) in a copy of tvp_ctrl.v (negative controls).
    With trace=1, also decodes only the resolved SCL/SDA pin samples from the bench.
    tag: appended to the build directory when two tests run the same bench."""
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    # one build directory per alteration: the negative controls may run in separate processes at once
    work = HERE / 'build' / f'tb_tvp_ctrl_{present1}{split}{scenario}_{trace}{"_alt" + hashlib.md5((alter[0] + alter[1]).encode()).hexdigest()[:6] if alter else ""}{tag}'
    work.mkdir(parents=True, exist_ok=True)
    ctrl = GW / 'rtl' / 'tvp_ctrl.v'
    if alter:
        text = ctrl.read_text()
        assert text.count(alter[0]) == 1
        ctrl = work / 'tvp_ctrl.v'
        ctrl.write_text(text.replace(*alter))
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_tvp_ctrl', f'-Ptb_tvp_ctrl.PRESENT1={present1}',
                    f'-Ptb_tvp_ctrl.SPLIT={split}', f'-Ptb_tvp_ctrl.SCENARIO={scenario}',
                    f'-Ptb_tvp_ctrl.PIN_TRACE={trace}',
                    str(GW / 'rtl' / 'i2c_master.v'), str(ctrl),
                    str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_tvp_ctrl.v')], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    line = next(l for l in out.splitlines() if l.startswith('RESULT'))
    assert 'timeout' not in line, out[-2000:]
    mid = next((l for l in out.splitlines() if l.startswith('MID')), None)
    fields = lambda l: dict(re.findall(r'(\w+)=(\w+)', l))
    r = fields(line)
    r['log'] = re.findall(r'^I2C W (\w\w) (\w\w)$', out, re.M)       # decoder 0's writes, in order
    if trace:
        events = parse_bus_text(out)
        r['transactions'] = decode_i2c_pin_trace(events, 'split_sda' if split else 'shared_sda')
        r['requests'] = [(int(t), value) for t, value in re.findall(r'^REQ (\d+) ([TV])$', out, re.M)]
        r['trace_output'] = out
    return r, fields(mid) if mid else None


def test_parse_bus_text_valid_rows():
    assert parse_bus_text('noise\nBUS 1 1 1 1\nBUS 2 0 1 0\n') == (
        (1, 1, 1, 1), (2, 0, 1, 0))


@pytest.mark.parametrize('malformed', [
    'BUS 3 X 1 1', 'BUS 3 1 X 1', 'BUS 3 1 1 X', 'BUS 3 1 Z 1',
    'BUS 3 1 1', 'BUS 3 1 1 1 extra', 'BUS nope 1 1 1', 'BUS -3 1 1 1'
], ids=['x-scl', 'x-sda0', 'x-sda1', 'z-sda0', 'missing-field', 'extra-field',
        'nondecimal-time', 'negative-time'])
def test_run_rejects_malformed_bus_trace_before_physical_decode(malformed, monkeypatch, tmp_path):
    def unexpected_decode(*_args, **_kwargs):
        pytest.fail('malformed BUS text reached physical pin decoder')

    valid_result = 'RESULT reset_low=1 reset_falls=1 err=0\n'
    stdout = valid_result + 'BUS 1 1 1 1\nBUS 2 1 1 1\n' + malformed + '\nBUS 4 1 1 1\n'
    calls = []

    def fake_run(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:  # mocked compile; this raw-text unit test does not build HDL
            return subprocess.CompletedProcess(args=[], returncode=0)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)

    monkeypatch.setattr(sys.modules[__name__], 'HERE', tmp_path)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(sys.modules[__name__], 'decode_i2c_pin_trace', unexpected_decode)
    with pytest.raises(TraceError):
        run(1, trace=1)
    assert len(calls) == 2, 'run(trace=1) must reach mocked stdout ingestion after mocked compile'


def test_run_rejects_empty_bus_trace_before_physical_decode(monkeypatch, tmp_path):
    def unexpected_decode(*_args, **_kwargs):
        pytest.fail('empty BUS text reached physical pin decoder')

    calls = []

    def fake_run(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:  # mocked compile; this raw-text unit test does not build HDL
            return subprocess.CompletedProcess(args=[], returncode=0)
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout='RESULT reset_low=1 reset_falls=1 err=0\n')

    monkeypatch.setattr(sys.modules[__name__], 'HERE', tmp_path)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(sys.modules[__name__], 'decode_i2c_pin_trace', unexpected_decode)
    with pytest.raises(TraceError, match='empty BUS trace'):
        run(1, trace=1)
    assert len(calls) == 2, 'run(trace=1) must reach mocked stdout ingestion after mocked compile'


def test_two_decoders():
    r, _ = run(1)
    assert r['reset_low'] == '1' and r['reset_falls'] == '1'
    assert r['err'] == '0'
    assert (r['s0_03'], r['s0_04'], r['s0_0d'], r['s0_00']) == (*INIT, '00')
    assert (r['s1_03'], r['s1_04'], r['s1_0d']) == INIT
    assert (r['s0_02'], r['s0_28']) == SET and (r['s1_02'], r['s1_28']) == SET
    assert r['s0_writes'] == str(N) and r['s1_writes'] == str(N)    # nothing is written again
    assert r['st0'] == ST_NTSC and r['st1'] == ST_PAL and r['valid'] == '3'
    assert r['reinit0'] == '0' and r['reinit1'] == '0'
    assert int(r['rounds0']) >= 3 and int(r['rounds1']) >= 3 and r['lost0'] == '0' and r['lost1'] == '0'


def test_missing_decoder_flagged():
    r, _ = run(0)
    assert r['err'] == '2'                      # decoder 1 (5Dh) did not acknowledge
    assert (r['s0_03'], r['s0_04'], r['s0_0d']) == INIT
    assert r['st0'] == ST_NTSC and r['valid'] == '1'
    assert r['reinit0'] == '0' and r['reinit1'] == '0'


def test_same_address_split_sda():
    """Two identical modules (both 5Ch) on separate SDA lines with a shared SCL."""
    r, _ = run(1, split=1)
    assert r['err'] == '0'
    assert (r['s0_03'], r['s0_04'], r['s0_0d']) == INIT and (r['s1_03'], r['s1_04'], r['s1_0d']) == INIT
    assert (r['s0_02'], r['s0_28']) == SET and (r['s1_02'], r['s1_28']) == SET
    assert r['s0_writes'] == str(N) and r['s1_writes'] == str(N)
    assert r['st0'] == ST_NTSC and r['st1'] == ST_PAL and r['valid'] == '3'


def test_reset_decoder_is_brought_up_again():
    """Decoder 1 loses its registers twice. Each time the list is written again and counted;
    RESETB is not pulsed and decoder 0 is left alone."""
    for split in (0, 1):
        r, mid = run(1, split=split, scenario=1)
        assert (mid['s1_03'], mid['s1_04'], mid['s1_0d']) == INIT and mid['reinit1'] == '1' and mid['s1_writes'] == str(2 * N)
        assert (mid['s1_02'], mid['s1_28']) == SET
        assert (r['s1_03'], r['s1_04'], r['s1_0d']) == INIT and r['reinit1'] == '2' and r['s1_writes'] == str(3 * N)
        assert r['reinit0'] == '0' and r['s0_writes'] == str(N) and r['s0_03'] == '0d'
        assert r['err'] == '0' and r['reset_falls'] == '1'


def test_reinit_counter_saturates():
    """A decoder that acknowledges writes but keeps 03h = 01h is retried in every poll round
    (more than 255 of them in this run): the counter stops at 255."""
    r, _ = run(1, scenario=2)
    assert r['s1_03'] == '01' and r['reinit1'] == '255'
    assert int(r['s1_writes']) > N * 256
    assert r['reinit0'] == '0' and r['s0_writes'] == str(N) and r['err'] == '0'
    assert r['st0'] == ST_NTSC and r['st1'] == ST_PAL            # status polling goes on
    assert r['valid'] == '1'                                     # ... but decoder 1 is never up


def test_sda_shorted_low_shows_in_the_counter():
    """An SDA line stuck low reads as acknowledge and as data 00h (i2c_master cannot tell), so
    the error flag stays clear. What gives it away is status 0000 with the counter at 255."""
    r, _ = run(1, split=1, scenario=4)
    assert r['err'] == '0' and r['st1'] == '0000' and r['reinit1'] == '255' and r['s1_writes'] == '0'
    assert r['reinit0'] == '0' and r['s0_writes'] == str(N) and r['st0'] == ST_NTSC
    assert r['valid'] == '1'                                     # 03h never reads 0Dh: decoder 1 never valid


@pytest.mark.parametrize('scenario', [5, 6, 7])
def test_failed_poll_round_is_not_valid(scenario):
    """Decoder 1 refuses 88h, 89h or 03h in one poll round; the other reads of that round
    succeed (review 2026-10-06, F2: a NACK on 88h was hidden by the ACK on 89h). Right after
    the round its status is not valid and the error flag is set; the words from before stay.
    The next whole round makes it valid again. A refused 03h is not a reset decoder."""
    r, mid = run(1, scenario=scenario)
    assert mid['err'] == '2' and mid['valid'] == '1' and mid['st1'] == ST_PAL, mid
    assert r['err'] == '0' and r['valid'] == '3' and r['st1'] == ST_PAL and r['st0'] == ST_NTSC, r
    assert r['reinit1'] == '0' and r['s1_writes'] == str(N)


def test_failed_poll_round_check_is_tested():
    """Negative control: a copy of tvp_ctrl.v that sets the error flag but leaves the status
    valid after a failed round is caught."""
    _, mid = run(1, scenario=5, alter=KEEP_VALID)
    assert mid['err'] == '2' and mid['valid'] == '3', mid


def test_late_decoder_and_error_flag():
    """Decoder 1 is not on the bus at start (error flag set), joins later (brought up, flag
    cleared: it is no longer sticky) and leaves again (flag set)."""
    r, mid = run(0, scenario=3)
    assert mid['err'] == '0' and mid['reinit1'] == '1' and mid['s1_writes'] == str(N)
    assert (mid['s1_03'], mid['s1_04'], mid['s1_0d']) == INIT and mid['valid'] == '3' and mid['st1'] == ST_PAL
    assert r['err'] == '2' and r['reinit1'] == '1' and r['s1_writes'] == str(N)
    assert r['reinit0'] == '0' and r['s0_writes'] == str(N)


WRONG_OP_MODE = ("parameter [7:0] OP_MODE = 8'h30", "parameter [7:0] OP_MODE = 8'h20")
WRONG_ORDER = ("3'd3: init_rom = {8'h28, VIDEO_STD};\n            3'd4: init_rom = {8'h02, selected_mode};",
               "3'd3: init_rom = {8'h02, selected_mode};\n            3'd4: init_rom = {8'h28, VIDEO_STD};")


def init_list_ok(r):
    return r['log'] == INIT_LIST and (r['s0_02'], r['s0_28']) == SET


def test_init_list_in_order():
    """Decoder 0 gets exactly the init list, in order, once: 28h (autoswitch) and 02h (TV mode)
    are written explicitly, 03h last (SLES209E 3.21.3, 3.21.32; README under M4)."""
    r, _ = run(1, tag='_init_list')
    assert r['log'] == INIT_LIST, r['log']
    assert init_list_ok(r)


@pytest.mark.parametrize('alter', [WRONG_OP_MODE, WRONG_ORDER], ids=['op_mode_vcr', 'order'])
def test_init_list_check_is_tested(alter):
    """Negative controls: 02h = 20h (VCR mode instead of TV), or 02h written before 28h."""
    r, _ = run(1, alter=alter)
    assert not init_list_ok(r), r['log']


WRONG_BIT = ("lost_lock[di] <= p88[4];", "lost_lock[di] <= p88[3];")


def test_lost_lock_flag():
    """Decoder 0 sets 88h bit 4 ("lost lock since 88h was last read") once. The next whole round
    reports it with its round_ok pulse, and only that round: reading 88h cleared the bit. Decoder 1
    never sets it (its 88h is 6Eh)."""
    r, _ = run(1, scenario=8)
    assert r['lost0'] == '1' and r['lost1'] == '0' and int(r['rounds0']) >= 3, r
    assert r['st0'] == ST_NTSC and r['valid'] == '3'


def test_lost_lock_bit_is_checked():
    """Negative control: bit 3 (colour lock, set on a healthy signal) taken for bit 4."""
    r, _ = run(1, scenario=8, alter=WRONG_BIT)
    assert r['lost0'] != '1' or r['lost1'] != '0', r


def _device_phases_acked(transaction):
    return all(sample.acknowledged for sample in transaction.acks if sample.actor == 'device')


def _mode_writes(transactions):
    return [tx for tx in transactions if tx.direction == 'write' and tx.register == 0x02]


def _read_key(transaction):
    return transaction.device, transaction.register


def _trace_state(transactions, requests):
    """Independent request/ACK ledger derived only from requests and physical bus records."""
    desired = 0x30
    acked = [None, None]
    request_index = 0
    for tx in transactions:
        while request_index < len(requests) and requests[request_index][0] <= tx.started_at:
            desired = 0x20 if requests[request_index][1] == 'V' else 0x30
            request_index += 1
        if tx.direction == 'write' and tx.register == 0x02 and tx.data and _device_phases_acked(tx):
            acked[tx.device] = tx.data[0]
        elif (tx.direction == 'read' and tx.register == 0x03 and tx.data and tx.data[0] != 0x0D
              and _device_phases_acked(tx)):
            acked[tx.device] = None
        while request_index < len(requests) and requests[request_index][0] <= tx.stopped_at:
            desired = 0x20 if requests[request_index][1] == 'V' else 0x30
            request_index += 1
    while request_index < len(requests):
        desired = 0x20 if requests[request_index][1] == 'V' else 0x30
        request_index += 1
    return desired, acked


def _first_midpoll_pair(transactions, requests):
    """Find the 88h transfer containing the first request, then require the rest of its pair."""
    assert requests, 'the pin-triggered mode request was not emitted'
    request_at, _value = requests[0]
    trigger = next((i for i, tx in enumerate(transactions)
                    if tx.direction == 'read' and tx.device == 0 and tx.register == 0x88
                    and tx.started_at <= request_at <= tx.stopped_at), None)
    if trigger is None:
        return None
    expected = ((0, 0x89), (0, 0x03), (1, 0x88), (1, 0x89), (1, 0x03))
    if tuple(_read_key(tx) for tx in transactions[trigger + 1:trigger + 6]) != expected:
        return None
    return trigger + 5


def _midpoll_mode_contract(result):
    """Return true only for full pair-before-service ordering and two ACKed VCR writes."""
    transactions = result['transactions']
    pair_end = _first_midpoll_pair(transactions, result['requests'])
    if pair_end is None or result['requests'][0][1] != 'V':
        return False
    desired, acked = _trace_state(transactions[:pair_end + 1], result['requests'])
    expected = [(device, desired) for device, value in enumerate(acked) if value != desired]
    actual = transactions[pair_end + 1:pair_end + 1 + len(expected)]
    return (desired == 0x20 and acked == [0x30, 0x30]
            and [(tx.device, tx.data[0] if tx.data else None) for tx in actual]
            == expected
            and all(tx.direction == 'write' and tx.register == 0x02 and not tx.aborted
                    and _device_phases_acked(tx) for tx in actual))


@pytest.mark.parametrize('split', [0, 1], ids=['shared-addresses', 'split-sda-lanes'])
def test_default_mode_init_is_visible_on_resolved_pins(split):
    r, _ = run(1, split=split, trace=1)
    modes = _mode_writes(r['transactions'])
    assert [(tx.device, tx.data) for tx in modes] == [(0, (0x30,)), (1, (0x30,))]
    assert all(tx.address == (0x5C if split else 0x5C + tx.device)
               and not tx.aborted and _device_phases_acked(tx) for tx in modes)


@pytest.mark.parametrize('split', [0, 1], ids=['shared-addresses', 'split-sda-lanes'])
def test_pin_trace_midpoll_request_waits_for_paired_poll_boundary(split):
    r, _ = run(1, split=split, scenario=9, trace=1)
    assert len(r['requests']) == 1 and r['requests'][0][1] == 'V'
    assert _midpoll_mode_contract(r), r['trace_output'][-3000:]
    pair_end = _first_midpoll_pair(r['transactions'], r['requests'])
    service = r['transactions'][pair_end + 1:pair_end + 3]
    assert [(tx.device, tx.register, tx.data) for tx in service] == [
        (0, 0x02, (0x20,)), (1, 0x02, (0x20,))]


def test_pin_trace_latest_request_wins_without_mutating_inflight_byte():
    r, _ = run(1, scenario=10, trace=1)
    assert [value for _when, value in r['requests']] == ['V', 'T']
    second_at = r['requests'][1][0]
    modes = [tx for tx in _mode_writes(r['transactions']) if tx.started_at > r['requests'][0][0]]
    assert [(tx.device, tx.data) for tx in modes] == [(0, (0x20,)), (0, (0x30,))]
    assert modes[0].started_at < second_at < modes[0].stopped_at
    desired, acked = _trace_state(r['transactions'], r['requests'])
    assert desired == 0x30 and acked == [0x30, 0x30]
    assert (r['s0_02'], r['s1_02']) == ('30', '30')


@pytest.mark.parametrize('split', [0, 1], ids=['shared-addresses', 'split-sda-lanes'])
def test_pin_trace_mode_nack_retries_after_polling_without_starvation(split):
    r, _ = run(1, split=split, scenario=11, trace=1)
    assert [value for _when, value in r['requests']] == ['V']
    _assert_mode_nack_pair_contract(r)


MODE_NACK_SKIP_DECODER1 = (
    "            end else if (ret == S_MODE) begin\n"
    "                if (!mode_cursor) begin mode_cursor <= 1'b1; st <= S_MODE; end\n"
    "                else begin mode_cursor <= 1'b0; di <= 0; ii <= 0; t <= 0; st <= S_POLL; end",
    "            end else if (ret == S_MODE) begin\n"
    "                if (!mode_cursor && !nack) begin mode_cursor <= 1'b1; st <= S_MODE; end\n"
    "                else begin mode_cursor <= 1'b0; di <= 0; ii <= 0; t <= 0; st <= S_POLL; end")


def _assert_mode_nack_pair_contract(result):
    transactions = result['transactions']
    request_at = result['requests'][0][0]
    modes = _mode_writes(transactions)
    first_nack = next((tx for tx in modes if tx.device == 0 and tx.started_at > request_at), None)
    assert first_nack is not None, 'decoder 0 mode NACK was not visible on the resolved bus'
    assert first_nack.data == (0x20,) and not first_nack.aborted, first_nack
    assert [(sample.phase, sample.acknowledged) for sample in first_nack.acks] == [
        ('address', True), ('register', False), ('data', False)], first_nack
    nack_at = transactions.index(first_nack)

    decoder1_at = nack_at + 1
    decoder1 = transactions[decoder1_at] if decoder1_at < len(transactions) else None
    assert (decoder1 is not None and decoder1.device == 1 and decoder1.direction == 'write'
            and decoder1.register == 0x02 and decoder1.data == (0x20,) and not decoder1.aborted
            and len(decoder1.acks) == 3 and _device_phases_acked(decoder1)), (
        'decoder 1 mode ACK must follow decoder 0 NACK before the paired poll')

    expected_pair = ((0, 0x88), (0, 0x89), (0, 0x03), (1, 0x88), (1, 0x89), (1, 0x03))
    pair_start = decoder1_at + 1
    assert tuple(_read_key(tx) for tx in transactions[pair_start:pair_start + 6]) == expected_pair, (
        'complete paired poll sweep must immediately follow decoder 1 mode ACK')
    pair_end = pair_start + len(expected_pair) - 1
    paired_reads = transactions[pair_start:pair_end + 1]
    assert all(tx.direction == 'read' and not tx.aborted and tx.data and _device_phases_acked(tx)
               for tx in paired_reads), 'paired poll contains an incomplete or unacknowledged read'

    retry_at = pair_end + 1
    retry = transactions[retry_at] if retry_at < len(transactions) else None
    assert (retry is not None and retry.device == 0 and retry.direction == 'write'
            and retry.register == 0x02 and retry.data == (0x20,) and not retry.aborted
            and _device_phases_acked(retry)), (
        'decoder 0 mode retry must ACK immediately after the complete paired poll')
    assert (result['s0_02'], result['s1_02']) == ('20', '20')


@pytest.mark.parametrize('split', [0, 1], ids=['shared-addresses', 'split-sda-lanes'])
def test_pin_trace_mode_nack_oracle_rejects_skip_decoder1_mutant(split):
    # run()'s unique-anchor assertion and HDL compile/execute stay outside the
    # expected oracle failure, so setup failures cannot count as mutant evidence.
    mutant, _ = run(1, split=split, scenario=11, alter=MODE_NACK_SKIP_DECODER1, trace=1)
    with pytest.raises(AssertionError, match='decoder 1 mode ACK must follow decoder 0 NACK'):
        _assert_mode_nack_pair_contract(mutant)


def test_startup_request_and_reset_reinit_preserve_vcr_selection():
    startup, _ = run(1, scenario=12, trace=1)
    init_modes = _mode_writes(startup['transactions'])
    assert [(tx.device, tx.data) for tx in init_modes] == [(0, (0x20,)), (1, (0x20,))]
    assert (startup['s0_02'], startup['s1_02']) == ('20', '20')

    reset, _ = run(1, scenario=13, trace=1)
    reset_read = next(i for i, tx in enumerate(reset['transactions'])
                      if tx.direction == 'read' and tx.device == 1 and tx.register == 0x03
                      and tx.data == (0x01,))
    reinit = reset['transactions'][reset_read + 1:reset_read + 1 + N]
    expected = ((0x00, 0x00), (0x04, 0xFC), (0x0D, 0x47), (0x28, 0x00), (0x02, 0x20), (0x03, 0x0D))
    assert [(tx.device, tx.register, tx.data[0] if tx.data else None) for tx in reinit] == [
        (1, register, value) for register, value in expected]
    assert (reset['s1_02'], reset['reinit1']) == ('20', '2')


WRONG_MODE_REGISTER = ("addr <= 8'h02; wdata <= selected_mode;", "addr <= 8'h03; wdata <= selected_mode;")
WRONG_MODE_MAPPING = ("selected_mode <= op_mode_vcr ? 8'h20 : 8'h30;",
                      "selected_mode <= op_mode_vcr ? 8'h30 : 8'h20;")
MODE_POLL_PREEMPT = (
    "if (di == N_DEV - 1) begin\n                di <= 0; t <= 0; mode_cursor <= 0; st <= S_MODE;",
    "if (di == N_DEV - 1 || (di == 0 && selected_mode == 8'h20)) begin\n                di <= 0; t <= 0; mode_cursor <= 0; st <= S_MODE;")


@pytest.mark.parametrize('alter', [WRONG_MODE_REGISTER, WRONG_MODE_MAPPING, MODE_POLL_PREEMPT],
                         ids=['wrong-register', 'wrong-TV-VCR-mapping', 'poll-preemption'])
def test_pin_trace_mode_contract_rejects_controller_mutations(alter):
    # The preemption mutant services decoder 0 after its triplet but before decoder 1's paired poll.
    r, _ = run(1, scenario=9, alter=alter, trace=1)
    if alter == MODE_POLL_PREEMPT:
        assert len(r['requests']) == 1 and r['requests'][0][1] == 'V'
        request_at = r['requests'][0][0]
        trigger = next(i for i, tx in enumerate(r['transactions'])
                       if tx.direction == 'read' and tx.device == 0 and tx.register == 0x88
                       and tx.started_at <= request_at <= tx.stopped_at)
        after = r['transactions'][trigger + 1:trigger + 4]
        assert tuple(_read_key(tx) for tx in after[:2]) == ((0, 0x89), (0, 0x03))
        assert len(after) == 3 and after[2].direction == 'write' and after[2].device == 0
        assert after[2].register == 0x02 and after[2].data == (0x20,)
        assert _device_phases_acked(after[2]), 'preemption did not produce an actual ACKed early mode write'
    assert not _midpoll_mode_contract(r), (
        'controller mutation violated the independent paired-poll/mode-service ordering oracle; '
        + r['trace_output'][-3000:])
