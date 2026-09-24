import pytest
from pmkmacro import midi


def test_channel_messages():
    assert midi.note_on(60, 127, 1) == bytes([0x90, 60, 127])
    assert midi.note_off(60, 0, 16) == bytes([0x8F, 60, 0])
    assert midi.control_change(7, 200, 2) == bytes([0xB1, 7, 127])  # clamped
    assert midi.program_change(5, 10) == bytes([0xC9, 5])


def test_bad_channel():
    with pytest.raises(ValueError):
        midi.note_on(60, 100, 0)


def test_msc_go_with_cue_and_list():
    data = midi.msc("go", cue="1.5", cue_list="2", device_id=1, command_format="lighting")
    assert data == bytes([0xF0, 0x7F, 0x01, 0x02, 0x01, 0x01]) + b"1.5\x002" + bytes([0xF7])


def test_msc_go_without_cue():
    assert midi.msc("go") == bytes([0xF0, 0x7F, 0x7F, 0x02, 0x7F, 0x01, 0xF7])


def test_msc_fire_and_set():
    assert midi.msc("fire", macro=5)[-2:] == bytes([5, 0xF7])
    data = midi.msc("set", control=200, value=16383)
    assert data[6:10] == bytes([200 & 0x7F, 200 >> 7, 0x7F, 0x7F])


def test_msc_errors():
    with pytest.raises(ValueError):
        midi.msc("jump")
    with pytest.raises(ValueError):
        midi.msc("fire")
    with pytest.raises(ValueError):
        midi.msc("go", cue_list="1")  # list without cue
