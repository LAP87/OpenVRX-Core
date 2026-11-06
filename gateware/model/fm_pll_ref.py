"""Integer phase/frequency tracking experiment for Core #28, not an RTL design.

Phase is an unsigned 32-bit turn; signed errors wrap at half a turn. For each
quantised complex sample, e = measured_phase - predicted_phase. The frequency
integrator adds e/32, the next phase adds frequency + 3e/8. With gating, e is
weighted by min(2, sample_power / mean_power); mean power is an IIR with 1/256
gain in Q8. Near-zero vectors therefore exert little phase correction.

For sample n: e[n] = wrap(theta[n] - p[n]); f[n] = f[n-1] + e[n]/32;
u[n] = f[n] + 3e[n]/8; p[n+1] = p[n] + u[n]. Weighting precedes these
updates, divisions round down, f saturates to a signed half turn/sample and
p wraps modulo one turn. step returns u, the predicted phase increment,
not the frequency integrator f. It has quantisation ripple and a dynamic
response; no signal alignment is hidden in its conversion to video.

Only LUT generation uses atan2. step() uses integer lookups and arithmetic.
The full phase LUT is an ideal detector model, not a claim about FPGA cost,
CORDIC accuracy, physical sampling or achievable RF sensitivity. No external
demodulator source code is used.
"""
from functools import lru_cache
import math

TURN = 1 << 32
HALF = TURN >> 1
MASK = TURN - 1


def wrap_error(value):
    return ((value + HALF) & MASK) - HALF


@lru_cache(maxsize=4)
def phase_table(bits):
    if not 2 <= bits <= 8:
        raise ValueError('phase LUT supports 2..8 bits per axis')
    limit = 1 << (bits-1)
    return {(i, q): round(math.atan2(q, i)*TURN/(2*math.pi))
            for i in range(-limit, limit) for q in range(-limit, limit) if i or q}


class FMPLL:
    def __init__(self, bits, gated=True, loop_sign=1):
        if loop_sign not in (-1, 1):
            raise ValueError('loop sign must be +1 or the explicit -1 negative control')
        self.table = phase_table(bits)
        self.gated, self.loop_sign = gated, loop_sign
        self.phase = self.frequency = self.power_q8 = 0
        self.last_weight_q8 = 0

    def step(self, i, q):
        power = i*i + q*q
        if self.power_q8 == 0:
            self.power_q8 = power << 8
        else:
            self.power_q8 += ((power << 8) - self.power_q8) >> 8
        if power:
            measured = self.table[(i, q)]
            weight = min(512, (power << 16)//max(self.power_q8, 1)) if self.gated else 256
            correction = self.loop_sign * (wrap_error(measured-self.phase)*weight//256)
        else:
            weight = correction = 0  # phase is undefined at the origin: coast on frequency
        self.last_weight_q8 = weight
        self.frequency = max(-HALF, min(HALF-1, self.frequency + (correction >> 5)))
        increment = self.frequency + ((3*correction) >> 3)
        self.phase = (self.phase + increment) & MASK
        return increment
