"""Physical key numbering.

PMK numbers keys in columns from the bottom-left (USB connector at the top):

    3  7  11  15
    2  6  10  14
    1  5   9  13
    0  4   8  12

The Pico RGB Keypad Base is remapped by PMK to the same numbering.
"""

NUM_KEYS = 16
COLS = 4
ROWS = 4


def key_to_cell(key, rotation=0):
    """Key number -> (row, col) on screen, row 0 at the top."""
    col = key // ROWS
    row = ROWS - 1 - (key % ROWS)
    for _ in range((rotation // 90) % 4):
        # rotate the grid 90 degrees clockwise
        row, col = col, ROWS - 1 - row
    return row, col


def cell_to_key(row, col, rotation=0):
    for key in range(NUM_KEYS):
        if key_to_cell(key, rotation) == (row, col):
            return key
    raise ValueError("no key at %s,%s" % (row, col))


def satellite_index(key, rotation=0):
    """Companion Satellite key index: left-to-right, top-to-bottom."""
    row, col = key_to_cell(key, rotation)
    return row * COLS + col


def key_from_satellite(index, rotation=0):
    return cell_to_key(index // COLS, index % COLS, rotation)
