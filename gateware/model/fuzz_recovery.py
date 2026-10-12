"""Append a clean synchronized recovery interval to an immutable fuzz prefix."""
import copy
import math

import bt656 as receiver_model
import fuzz_stream as generator

def append_camera_fields(original, fields=4):
    """Return a new scenario and recovery metadata; retain every original byte/control.

    The appended fields are clean and their starts are synchronized after blanking.
    Original channel offset remains in the prefix, not the new recovery phase.
    This API does not change generate() or enable recovery in a campaign.
    """
    if type(fields) is not int or fields <= 0:
        raise ValueError('fields must be a positive integer')
    if original.geometry not in generator.GEOM or original.std not in generator.GEOM[original.geometry]:
        raise ValueError('unknown geometry or video standard')
    periods = (original.t_a, original.t_b)
    if any(not math.isfinite(value) or value <= 0 for value in periods):
        raise ValueError('byte clocks must have finite positive periods')
    if any(not math.isfinite(value) for value in (original.start_a, original.start_b)):
        raise ValueError('input start times must be finite')
    scenario = copy.deepcopy(original)
    geometry = generator.GEOM[original.geometry][original.std]
    active, vbi = geometry['lines'], geometry['vbi']
    hb = geometry['line'] - generator.ACTIVE - 8
    ends = (original.start_a + len(original.a) * periods[0],
            original.start_b + len(original.b) * periods[1])
    target = max(ends) + geometry['line'] * max(periods)
    padding, suffix_starts = {}, {}
    first_field = len(original.camera)
    for channel in (0, 1):
        prefix = original.a if channel == 0 else original.b
        start = original.start_a if channel == 0 else original.start_b
        pad = math.ceil((target - ends[channel]) / periods[channel])
        pad += pad % 2
        padding[channel] = pad
        suffix_starts[channel] = start + (len(prefix) + pad) * periods[channel]
        stream = bytearray(prefix) + receiver_model.blanking(pad)
        for field in range(first_field, first_field + fields):
            blank_lines = vbi + ((field & 1) if original.interlaced else 0)
            f_bit = field & 1 if original.interlaced else 1
            for i in range(blank_lines + active):
                blank = i < blank_lines
                n = -1 if blank else i - blank_lines
                line = generator.Line(k=field, i=i, v=int(blank), f=f_bit, n=n, hb=hb,
                                      act=None if blank else generator.active_bytes(field, n, 0, None))
                line.pos = len(stream)
                eav = bytes((255, 0, 0, receiver_model.xy(f_bit, int(blank), 1)))
                sav = bytes((255, 0, 0, receiver_model.xy(f_bit, int(blank), 0)))
                payload = receiver_model.blanking(generator.ACTIVE) if blank else line.act
                stream += eav + receiver_model.blanking(hb) + sav + payload
                scenario.lines[channel].append(line)
        stream += bytes((255, 0, 0, receiver_model.xy(1, 1, 1))) + receiver_model.blanking(64)
        if channel == 0:
            scenario.a = bytes(stream)
        else:
            scenario.b = bytes(stream)
    scenario.camera.extend((vbi + ((field & 1) if original.interlaced else 0), active)
                           for field in range(first_field, first_field + fields))
    scenario.end_ns = max(scenario.start_a + len(scenario.a) * scenario.t_a,
                          scenario.start_b + len(scenario.b) * scenario.t_b)
    return scenario, dict(fields=fields, first_field=first_field, active_lines=active,
                          base_vbi=vbi, padding_bytes=padding, suffix_start_ns=suffix_starts,
                          source_end_ns=scenario.end_ns,
                          kind='synchronized clean recovery; original byte clocks retained')
