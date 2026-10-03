import pytest

from scripts.choch_fvg import (
    find_choch,
    find_fvgs,
    find_ifvgs,
    find_structure_breaks,
    find_swings,
)


def test_bullish_fvg_and_mitigation():
    highs = [10, 12, 15, 14, 13]
    lows = [9, 10, 11, 12, 9]
    gaps = find_fvgs(highs, lows)
    assert len(gaps) == 1
    g = gaps[0]
    assert (g.index, g.direction, g.top, g.bottom) == (2, "bullish", 11, 10)
    assert g.mitigated_index == 4


def test_bearish_fvg():
    highs = [10, 9, 7]
    lows = [9, 7, 5]
    gaps = find_fvgs(highs, lows)
    assert [(g.direction, g.top, g.bottom) for g in gaps] == [("bearish", 9, 7)]
    assert gaps[0].mitigated_index is None


def test_fvg_min_size_filters_small_gaps():
    highs = [10, 12, 15]
    lows = [9, 10, 10.5]
    assert len(find_fvgs(highs, lows)) == 1
    assert find_fvgs(highs, lows, min_size=1) == []


def test_ifvg_created_when_close_breaks_bullish_fvg():
    # FVG alcista [10, 11] en la vela 2; la vela 3 entra con la mecha (no invierte),
    # la vela 4 cierra por debajo de 10 -> IFVG bajista creado en 4.
    highs = [10, 12, 15, 14, 12]
    lows = [9, 10, 11, 9.5, 8]
    closes = [9.5, 11, 14, 12, 8.5]
    ifvgs = find_ifvgs(highs, lows, closes)
    assert len(ifvgs) == 1
    i = ifvgs[0]
    assert (i.index, i.direction, i.top, i.bottom, i.source_index) == (4, "bearish", 11, 10, 2)


def test_ifvg_from_bearish_fvg():
    highs = [10, 9, 7, 8, 11]
    lows = [9, 7, 5, 6, 9]
    closes = [9.5, 8, 6, 7.5, 10]
    ifvgs = find_ifvgs(highs, lows, closes)
    assert [(i.index, i.direction, i.top, i.bottom) for i in ifvgs] == [(4, "bullish", 9, 7)]


def test_swings():
    highs = [1, 2, 5, 2, 1]
    lows = [0.5, 1, 4, 1, 0]
    sh, sl = find_swings(highs, lows, 2)
    assert sh == [(2, 5)]
    assert sl == []


def test_bos_then_choch():
    # Subida con swing high en 2, retroceso con swing low en 5,
    # ruptura alcista (BOS) y luego ruptura del swing low (CHoCH bajista).
    highs = [2, 3, 5, 4, 3.5, 3, 4, 6, 5, 4, 2]
    lows = [1, 2, 4, 3, 2.5, 2, 3, 5, 4, 3, 1]
    closes = [1.5, 2.5, 4.5, 3.5, 3, 2.5, 3.5, 5.5, 4.5, 3.5, 1.5]
    events = find_structure_breaks(highs, lows, closes, swing_length=1)
    assert [(e.index, e.kind, e.direction, e.level) for e in events] == [
        (7, "BOS", "bullish", 5),
        (10, "CHoCH", "bearish", 2),
    ]
    assert [e.index for e in find_choch(highs, lows, closes, swing_length=1)] == [10]


def test_no_lookahead_swing_not_used_before_confirmation():
    highs = [1, 3, 1, 4]
    lows = [0, 2, 0, 3]
    closes = [0.5, 2.5, 0.5, 3.5]
    # swing high en 1 se confirma en 2 (length=1); rompe en 3.
    events = find_structure_breaks(highs, lows, closes, swing_length=1)
    assert [(e.index, e.swing_index) for e in events] == [(3, 1)]


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        find_fvgs([1, 2], [1])
    with pytest.raises(ValueError):
        find_ifvgs([1, 2, 3], [1, 2, 3], [1, 2])
