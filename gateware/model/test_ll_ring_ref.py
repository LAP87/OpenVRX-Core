import pytest

import ll_ring_ref as ring


def write_line(buf, slot, first_time=0.0, word_base=0x10000000):
    for index in range(ring.LINE_WORDS):
        value = word_base + index
        buf.accept_write(slot * ring.SLOT_WORDS + index, value, first_time + index)
    return word_base + 52


def test_midline_entry_ending_at_359_does_not_initialize_virgin_slot():
    buf = ring.LineBuffer()
    slot = 9
    for index in range(53, ring.LINE_WORDS):
        buf.accept_write(slot * ring.SLOT_WORDS + index, 0xAA000000 + index, index)
    assert not buf.valid_at(slot)
    assert buf.expected(slot, 52, read_time_ns=500, valid_time_ns=500) == ring.BLACK_WORD


def test_only_contiguous_full_slot_write_initializes_and_exposes_sample():
    buf = ring.LineBuffer()
    slot = 7
    expected = write_line(buf, slot, word_base=0x23000000)
    assert buf.valid_at(slot)
    assert buf.expected(slot, 52, read_time_ns=1000, valid_time_ns=1000) == expected


@pytest.mark.parametrize('fault', ['gap', 'wrong_slot', 'wrong_start'])
def test_malformed_first_line_never_initializes(fault):
    buf = ring.LineBuffer()
    slot = 6
    addresses = list(range(slot * ring.SLOT_WORDS, slot * ring.SLOT_WORDS + ring.LINE_WORDS))
    if fault == 'gap':
        addresses.remove(slot * ring.SLOT_WORDS + 87)
    elif fault == 'wrong_slot':
        addresses[87] += ring.SLOT_WORDS
    else:
        addresses.pop(0)
    for i, address in enumerate(addresses):
        buf.accept_write(address, 0x45000000 + i, i)
    assert not buf.valid_at(slot)
    assert buf.expected(slot, 52, read_time_ns=2000, valid_time_ns=2000) == ring.BLACK_WORD


def test_initialized_slot_retains_stale_word_and_partial_writes_do_not_clear_it():
    buf = ring.LineBuffer()
    slot = 3
    old = write_line(buf, slot, word_base=0x32000000)
    assert buf.expected(slot, 52, read_time_ns=1000, valid_time_ns=1000) == old

    # A missing later line leaves the old sample available.
    assert buf.expected(slot, 52, read_time_ns=1100, valid_time_ns=1100) == old

    # A partial overwrite that does not reach word 52 keeps the old sample.
    for index in range(10):
        buf.accept_write(slot * ring.SLOT_WORDS + index, 0x55000000 + index, 1200 + index)
    assert buf.valid_at(slot)
    assert buf.expected(slot, 52, read_time_ns=1400, valid_time_ns=1400) == old

    # If a later partial line reaches word 52, the RAM's actual new word is still expected.
    buf.accept_write(slot * ring.SLOT_WORDS + 52, 0xDEADBEEF, 1500)
    assert buf.valid_at(slot)
    assert buf.expected(slot, 52, read_time_ns=1600, valid_time_ns=1600) == 0xDEADBEEF


def test_validity_survives_other_slot_writes_and_clears_only_on_reset():
    buf = ring.LineBuffer()
    expected = write_line(buf, 2, word_base=0x17000000)
    write_line(buf, 10, first_time=500, word_base=0x27000000)
    assert buf.valid_at(2) and buf.valid_at(10)
    assert buf.expected(2, 52, read_time_ns=2000, valid_time_ns=2000) == expected

    buf.reset()
    assert not buf.valid_at(2) and not buf.valid_at(10)
    assert buf.words[2 * ring.SLOT_WORDS + 52] == expected  # RAM itself has no reset
    assert buf.expected(2, 52, read_time_ns=2000, valid_time_ns=2000) == ring.BLACK_WORD


def test_pixel_pipeline_aligns_validity_with_the_registered_ram_word():
    buf = ring.LineBuffer()
    pixel = ring.PixelReadPipeline()
    slot_valid, slot_virgin = 4, 9
    word = write_line(buf, slot_valid, word_base=0x71000000)
    # First edge samples the valid mask, while the RAM captures slot_valid.
    assert pixel.posedge(buf, slot_valid * ring.SLOT_WORDS + 52, True) is None
    # On the next display-consume edge, the synchronizer has not yet reached stage 2.
    assert pixel.posedge(buf, slot_virgin * ring.SLOT_WORDS + 52, True) == ring.BLACK_WORD
    # The second-stage mask and data address advance together. The prior word is valid.
    assert pixel.posedge(buf, slot_valid * ring.SLOT_WORDS + 52, True) == ring.BLACK_WORD
    assert pixel.posedge(buf, slot_virgin * ring.SLOT_WORDS + 52, True) == word
    assert pixel.posedge(buf, slot_virgin * ring.SLOT_WORDS + 52, True) == ring.BLACK_WORD


def test_reset_flushes_pixel_sync_and_read_pipeline():
    buf = ring.LineBuffer()
    pixel = ring.PixelReadPipeline()
    write_line(buf, 1, word_base=0x41000000)
    pixel.posedge(buf, 1 * ring.SLOT_WORDS + 52, True)
    pixel.posedge(buf, 1 * ring.SLOT_WORDS + 52, True)
    pixel.reset()
    buf.reset()
    assert pixel.posedge(buf, 1 * ring.SLOT_WORDS + 52, True) is None
    pixel.posedge(buf, 1 * ring.SLOT_WORDS + 52, True)
    assert pixel.display_input(buf) == ring.BLACK_WORD
