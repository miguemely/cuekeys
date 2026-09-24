# SPDX-License-Identifier: MIT
"""Raw MIDI message builders.

Pure Python with no CircuitPython dependencies, so the same code runs on the
keypad (written straight to ``usb_midi.ports[1]``) and in desktop tests.
Channels are 1-16 (as printed on consoles), everything else is 0-127.
"""

# MIDI Show Control command bytes (MSC 1.0 spec).
MSC_COMMANDS = {
    "go": 0x01,
    "stop": 0x02,
    "resume": 0x03,
    "timed_go": 0x04,
    "load": 0x05,
    "set": 0x06,
    "fire": 0x07,
    "all_off": 0x08,
    "restore": 0x09,
    "reset": 0x0A,
    "go_off": 0x0B,
}

# MSC command formats. grandMA2/3 default to "lighting" (0x01) or "all" (0x7F).
MSC_FORMATS = {
    "lighting": 0x01,
    "moving_lights": 0x02,
    "all": 0x7F,
}


def _clamp7(value):
    value = int(value)
    if value < 0:
        return 0
    if value > 127:
        return 127
    return value


def _status(kind, channel):
    channel = int(channel)
    if channel < 1 or channel > 16:
        raise ValueError("MIDI channel must be 1-16")
    return kind | (channel - 1)


def note_on(note, velocity=127, channel=1):
    return bytes((_status(0x90, channel), _clamp7(note), _clamp7(velocity)))


def note_off(note, velocity=0, channel=1):
    return bytes((_status(0x80, channel), _clamp7(note), _clamp7(velocity)))


def control_change(cc, value, channel=1):
    return bytes((_status(0xB0, channel), _clamp7(cc), _clamp7(value)))


def program_change(program, channel=1):
    return bytes((_status(0xC0, channel), _clamp7(program)))


def _ascii(text):
    out = bytearray()
    for ch in str(text):
        code = ord(ch)
        if code > 127:
            raise ValueError("MSC fields must be ASCII")
        out.append(code)
    return out


def msc(command, cue=None, cue_list=None, cue_path=None, device_id=0x7F,
        command_format="all", macro=None, control=None, value=None):
    """Build a MIDI Show Control SysEx message.

    ``F0 7F <device_id> 02 <format> <command> <data...> F7``

    * go / stop / resume / load / go_off: optional ``cue`` / ``cue_list`` /
      ``cue_path`` as ASCII numbers ("1.5"), separated by 0x00.
      On grandMA2 in "Exec.Page" mode ``cue_list`` is "executor.page" (e.g. "1.1").
    * fire: ``macro`` 0-127.
    * set: ``control`` 0-16383 and ``value`` 0-16383 (both 14-bit LSB first).
    """
    if command not in MSC_COMMANDS:
        raise ValueError("unknown MSC command: %s" % command)
    fmt = command_format
    if not isinstance(fmt, int):
        if fmt not in MSC_FORMATS:
            raise ValueError("unknown MSC command format: %s" % fmt)
        fmt = MSC_FORMATS[fmt]
    out = bytearray((0xF0, 0x7F, _clamp7(device_id), 0x02, fmt & 0x7F,
                     MSC_COMMANDS[command]))
    if command == "fire":
        if macro is None:
            raise ValueError("MSC fire needs a macro number")
        out.append(_clamp7(macro))
    elif command == "set":
        if control is None or value is None:
            raise ValueError("MSC set needs control and value")
        control = max(0, min(16383, int(control)))
        value = max(0, min(16383, int(value)))
        out.extend((control & 0x7F, control >> 7, value & 0x7F, value >> 7))
    else:
        fields = [cue, cue_list, cue_path]
        # Trailing empty fields are omitted; inner ones must exist.
        while fields and fields[-1] in (None, ""):
            fields.pop()
        for i, field in enumerate(fields):
            if field in (None, ""):
                raise ValueError("MSC cue_list/cue_path need a cue")
            if i:
                out.append(0x00)
            out.extend(_ascii(field))
    out.append(0xF7)
    return bytes(out)
