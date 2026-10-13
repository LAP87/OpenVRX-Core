"""Reference for i2c_master.v transactions against a TVP5150-like register slave.

What should appear on the bus, what the slave stores and what the master reports
(nack, number of wreq pulses) for each transaction. Used by sim/test_i2c_master.py,
whose testbench drives i2c_master.v against sim/i2c_slave_model.v.

Bus events: 'S' (START or repeated START), 'P' (STOP), ('B', byte, ack_bit) with
ack_bit 0 = acknowledged, 1 = not.

Rules of the master (i2c_master.v):
- write: S, dev+W, reg, data 0 .. data n, P. A multi-byte write (n > 0) sends P right
  after the first byte that is not acknowledged; a single-byte write sends all its
  bytes. wreq pulses once for each data byte that has a successor, when that byte
  starts on the bus, so not for bytes skipped after a NACK.
- read: S, dev+W, reg, Sr, dev+R, data with NACK from the master, P. With two bytes per read
  (READ_BYTES = 2) the master ACKs the first and NACKs the second; the value is MSB first.
Rules of the slave (i2c_slave_model.v): register pointer set by the register byte and
advanced after every byte written or read (unless auto_inc is off); the data byte
with index nack_data is not acknowledged and not stored, nor is anything after it
in that write.
"""

TVP_DEFAULTS = {0x00: 0x00, 0x03: 0x01, 0x04: 0xDC, 0x0D: 0x00, 0x80: 0x51, 0x81: 0x50, 0x88: 0x0E, 0x89: 0x00}


class Slave:
    def __init__(self, addr=0x5C, auto_inc=True):
        self.addr = addr
        self.auto_inc = auto_inc
        self.regs = [TVP_DEFAULTS.get(i, 0) for i in range(256)]
        self.writes = []                     # (register, data) in the order stored
        self.ptr = 0

    def _advance(self):
        if self.auto_inc:
            self.ptr = (self.ptr + 1) & 0xFF


def write(slave, dev, reg, data, nack_data=-1):
    """(bus events, nack, wreq pulses) of one write of len(data) >= 1 bytes."""
    multi = len(data) > 1
    me = dev == slave.addr
    ev, nack, wreq = ['S'], False, 0
    for i, b in enumerate([dev << 1, reg, *data]):
        k = i - 2                            # data byte index
        if 0 <= k < len(data) - 1:
            wreq += 1
        if k < 0:
            ack = me
            if i == 1 and me:
                slave.ptr = reg
        elif me and k == nack_data:
            ack = me = False
        else:
            ack = me
            if me:
                slave.regs[slave.ptr] = b
                slave.writes.append((slave.ptr, b))
                slave._advance()
        ev.append(('B', b, 0 if ack else 1))
        nack |= not ack
        if multi and nack:
            break
    return ev + ['P'], nack, wreq


def read(slave, dev, reg, n=1):
    """(bus events, nack, data) of one register read of n bytes (data MSB first)."""
    me = dev == slave.addr
    a = 0 if me else 1
    data = []
    if me:
        slave.ptr = reg
        for _ in range(n):
            data.append(slave.regs[slave.ptr])
            slave._advance()
    else:
        data = [0xFF] * n                    # nobody drives SDA
    ev = ['S', ('B', dev << 1, a), ('B', reg, a), 'S', ('B', dev << 1 | 1, a)]
    ev += [('B', b, 1 if k == n - 1 else 0) for k, b in enumerate(data)] + ['P']
    value = 0
    for b in data:
        value = value << 8 | b
    return ev, not me, value
