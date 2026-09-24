from pmk_macro_manager.layout import cell_to_key, key_from_satellite, key_to_cell, satellite_index


def test_default_orientation():
    assert key_to_cell(0) == (3, 0)   # bottom-left
    assert key_to_cell(3) == (0, 0)   # top-left
    assert key_to_cell(15) == (0, 3)  # top-right
    assert satellite_index(3) == 0
    assert satellite_index(15) == 3
    assert satellite_index(0) == 12


def test_rotations_are_bijective_and_invertible():
    for rotation in (0, 90, 180, 270):
        cells = {key_to_cell(k, rotation) for k in range(16)}
        assert len(cells) == 16
        for k in range(16):
            assert cell_to_key(*key_to_cell(k, rotation), rotation) == k
            assert key_from_satellite(satellite_index(k, rotation), rotation) == k
