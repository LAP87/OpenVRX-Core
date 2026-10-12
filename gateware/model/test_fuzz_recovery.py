"""Recovery bytes against accepted native hashes and the BT.656 receiver, without RTL."""
import copy
import hashlib
import pickle

import pytest

import bt656
import fuzz_stream as fz
from fuzz_recovery import append_camera_fields

CASES = [({'label': 'scaled-d1', 'seed': 1200, 'geometry': 'scaled', 'density': 1.0, 'fields': 10, 'force': []}, 'ntsc', True), ({'label': 'scaled-d2p5', 'seed': 1345, 'geometry': 'scaled', 'density': 2.5, 'fields': 10, 'force': []}, 'ntsc', False), ({'label': 'scaled-bedge-d1', 'seed': 1400, 'geometry': 'scaled', 'density': 1.0, 'fields': 10, 'force': ['b_edge']}, 'ntsc', False), ({'label': 'scaled-bedge-d2p5', 'seed': 1425, 'geometry': 'scaled', 'density': 2.5, 'fields': 10, 'force': ['b_edge']}, 'pal', False), ({'label': 'full-d1', 'seed': 1500, 'geometry': 'full', 'density': 1.0, 'fields': 8, 'force': ['mode_switch']}, 'ntsc', True), ({'label': 'full-d2p5', 'seed': 1505, 'geometry': 'full', 'density': 2.5, 'fields': 8, 'force': ['mode_switch']}, 'pal', False), ({'label': 'explicit-scaled-pal', 'seed': 1600, 'geometry': 'scaled', 'density': 1.0, 'fields': 10, 'force': ['pal']}, 'pal', True), ({'label': 'explicit-full-pal', 'seed': 1601, 'geometry': 'full', 'density': 1.0, 'fields': 8, 'force': ['pal', 'mode_switch']}, 'pal', True), ({'label': 'explicit-progressive-pal', 'seed': 1602, 'geometry': 'scaled', 'density': 1.0, 'fields': 10, 'force': ['pal', 'progressive']}, 'pal', False)]

NATIVE_HEX_HASHES = {1345: {'a': 'f43cc70cab8ace213c194219db49d120a42aad46f528cd16943086b367e6289b', 'b': 'f81cf17c391bfdcfbe712fedf90e9f9c7a890cb20e72dd33d685e0b139004af3'}, 1400: {'a': '2c4b2169089c68a753d1c3b302b077fb106717d3a8b21670e87ec9470527e120', 'b': '2aaf325ec6a50914b154a97ab806a511b5529de3fd51f3cde74c8cad660fbc3a'}, 1601: {'a': '792c237af3e4f42154ee09131d742d7132c95d813f8d70497723498d8246e36b', 'b': '533048a277ec8c422f57cdc6765430135d6bc676454ca1dc223558bb811fca22'}}


def assert_recovery(original, extended, info):
    assert extended.a.startswith(original.a), 'original A prefix'
    assert extended.b.startswith(original.b), 'original B prefix'
    assert extended.ctl == original.ctl
    assert extended.used == original.used
    assert extended.camera[:len(original.camera)] == original.camera
    for name in ('start_a', 'start_b', 't_a', 't_b', 'll0', 'std', 'interlaced', 'ahead'):
        assert getattr(extended, name) == getattr(original, name)
    for channel, data, prefix in [(0, extended.a, original.a), (1, extended.b, original.b)]:
        assert extended.lines[channel][:len(original.lines[channel])] == original.lines[channel]
        offset = len(prefix) + info['padding_bytes'][channel]
        receiver = bt656.Receiver()
        for byte in data[offset:]:
            receiver.push(byte)
        active = fz.GEOM[original.geometry][original.std]['lines']
        assert len(receiver.records) == active * info['fields'], 'decoder field count'
        assert [r.line_in_field for r in receiver.records] == list(range(active)) * info['fields']
        expected_f = [k & 1 if original.interlaced else 1
                      for k in range(len(original.camera), len(original.camera) + info['fields'])
                      for _ in range(active)]
        assert [r.field for r in receiver.records] == expected_f
        assert all(r.active_count == 1440 and r.length == fz.GEOM[original.geometry][original.std]['line']
                   and not r.xy_bad and not r.xy_corrected and not r.luma_outside
                   for r in receiver.records)
    assert extended.end_ns == max(extended.start_a + len(extended.a) * extended.t_a,
                                  extended.start_b + len(extended.b) * extended.t_b)
    assert abs(info['suffix_start_ns'][0] - info['suffix_start_ns'][1]) < 2 * max(original.t_a, original.t_b)


@pytest.mark.parametrize('case,std,interlaced', CASES, ids=[row[0]['label'] for row in CASES])
def test_recovery_matrix_and_native_bytes(case, std, interlaced):
    original = fz.generate(case['seed'], n_fields=case['fields'], force=case['force'],
                           density=case['density'], geometry=case['geometry'])
    assert original.std == std and original.interlaced == interlaced
    before = pickle.dumps(original)
    extended, info = append_camera_fields(original)
    assert pickle.dumps(original) == before, 'original mutated'
    assert_recovery(original, extended, info)
    if case['seed'] in NATIVE_HEX_HASHES:
        for channel, data in [('a', extended.a), ('b', extended.b)]:
            hex_file = ''.join(f'{byte:02x}\n' for byte in data).encode()
            assert hashlib.sha256(hex_file).hexdigest() == NATIVE_HEX_HASHES[case['seed']][channel]


@pytest.mark.parametrize('fields', [0, -1, True, False, 1.5, None])
def test_invalid_field_counts(fields):
    with pytest.raises(ValueError, match='positive integer'):
        append_camera_fields(None, fields=fields)


@pytest.mark.parametrize('field,value', [('geometry','unknown'),('std','unknown'),
                                       ('t_a',0),('t_b',float('nan')),
                                       ('t_a',float('inf')),('start_a',float('inf')),
                                       ('start_b',float('nan'))])
def test_invalid_scenario_metadata(field, value):
    original = fz.generate(1, classes=(), n_fields=1)
    setattr(original, field, value)
    with pytest.raises(ValueError):
        append_camera_fields(original)


@pytest.mark.parametrize('fault', ['prefix', 'truncated_field'])
def test_actual_stream_faults_fail_same_oracle(fault):
    original = fz.generate(1, classes=(), n_fields=2)
    extended, info = append_camera_fields(original)
    assert_recovery(original, extended, info)
    broken = copy.copy(extended)
    if fault == 'prefix':
        broken.a = bytes([extended.a[0] ^ 1]) + extended.a[1:]
        message = 'original A prefix'
    else:
        broken.a = extended.a[:-5000]
        message = 'decoder field count'
    with pytest.raises(AssertionError, match=message):
        assert_recovery(original, broken, info)


def test_nondefault_recovery_field_count():
    original = fz.generate(1, classes=(), n_fields=2)
    extended, info = append_camera_fields(original, fields=2)
    assert info['fields'] == 2
    assert_recovery(original, extended, info)
