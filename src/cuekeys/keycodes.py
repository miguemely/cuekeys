"""Key names understood by the firmware (adafruit_hid attribute names)."""

LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
DIGITS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "ZERO"]
FUNCTION = ["F%d" % i for i in range(1, 25)]

MODIFIERS = [
    "PRIMARY",  # COMMAND on macOS, CONTROL elsewhere (resolved on the keypad)
    "CONTROL", "LEFT_CONTROL", "RIGHT_CONTROL",
    "SHIFT", "LEFT_SHIFT", "RIGHT_SHIFT",
    "ALT", "LEFT_ALT", "RIGHT_ALT", "OPTION",
    "GUI", "LEFT_GUI", "RIGHT_GUI", "COMMAND", "WINDOWS",
]

NAVIGATION = [
    "ENTER", "RETURN", "ESCAPE", "BACKSPACE", "TAB", "SPACEBAR",
    "INSERT", "DELETE", "HOME", "END", "PAGE_UP", "PAGE_DOWN",
    "UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW",
    "PRINT_SCREEN", "SCROLL_LOCK", "PAUSE", "CAPS_LOCK", "APPLICATION",
]

PUNCTUATION = [
    "MINUS", "EQUALS", "LEFT_BRACKET", "RIGHT_BRACKET", "BACKSLASH", "POUND",
    "SEMICOLON", "QUOTE", "GRAVE_ACCENT", "COMMA", "PERIOD", "FORWARD_SLASH",
]

KEYPAD = [
    "KEYPAD_NUMLOCK", "KEYPAD_FORWARD_SLASH", "KEYPAD_ASTERISK", "KEYPAD_MINUS",
    "KEYPAD_PLUS", "KEYPAD_ENTER", "KEYPAD_PERIOD", "KEYPAD_EQUALS",
    "KEYPAD_ONE", "KEYPAD_TWO", "KEYPAD_THREE", "KEYPAD_FOUR", "KEYPAD_FIVE",
    "KEYPAD_SIX", "KEYPAD_SEVEN", "KEYPAD_EIGHT", "KEYPAD_NINE", "KEYPAD_ZERO",
]

KEYCODES = MODIFIERS + LETTERS + DIGITS + FUNCTION + NAVIGATION + PUNCTUATION + KEYPAD
KEYCODE_SET = frozenset(KEYCODES)

CONSUMER_CODES = [
    "PLAY_PAUSE", "STOP", "SCAN_NEXT_TRACK", "SCAN_PREVIOUS_TRACK",
    "FAST_FORWARD", "REWIND", "RECORD", "EJECT",
    "MUTE", "VOLUME_INCREMENT", "VOLUME_DECREMENT",
    "BRIGHTNESS_INCREMENT", "BRIGHTNESS_DECREMENT",
]

# Friendly aliases accepted when parsing a combo string like "ctrl+shift+s".
ALIASES = {
    "CTRL": "CONTROL", "CMD": "COMMAND", "WIN": "WINDOWS", "SUPER": "GUI",
    "META": "GUI", "OPT": "OPTION", "ESC": "ESCAPE", "DEL": "DELETE",
    "UP": "UP_ARROW", "DOWN": "DOWN_ARROW", "LEFT": "LEFT_ARROW",
    "RIGHT": "RIGHT_ARROW", "PGUP": "PAGE_UP", "PGDN": "PAGE_DOWN",
    "MOD": "PRIMARY", "CMDORCTRL": "PRIMARY", "SPACE": "SPACEBAR",
    "0": "ZERO", "1": "ONE", "2": "TWO", "3": "THREE", "4": "FOUR",
    "5": "FIVE", "6": "SIX", "7": "SEVEN", "8": "EIGHT", "9": "NINE",
    "-": "MINUS", "=": "EQUALS", "/": "FORWARD_SLASH", ".": "PERIOD", ",": "COMMA",
}


def parse_combo(text):
    """Parse "ctrl+shift+s" into ["CONTROL", "SHIFT", "S"].

    Raises ValueError for unknown names.
    """
    out = []
    for part in text.replace(" ", "").split("+"):
        if not part:
            continue
        name = part.upper()
        name = ALIASES.get(name, name)
        if name not in KEYCODE_SET:
            raise ValueError("unknown key: %s" % part)
        out.append(name)
    return out


def format_combo(keys):
    return "+".join(keys)
