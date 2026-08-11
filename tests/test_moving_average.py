import pytest

from scripts.moving_average import simple_moving_average


def test_basic_window():
    assert simple_moving_average([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]


def test_window_equals_length():
    assert simple_moving_average([1, 2, 3], 3) == [2.0]


def test_window_larger_than_prices_returns_empty():
    assert simple_moving_average([1, 2], 5) == []


def test_window_of_one_returns_prices_unchanged():
    assert simple_moving_average([1, 2, 3], 1) == [1.0, 2.0, 3.0]


def test_invalid_window_raises_value_error():
    with pytest.raises(ValueError):
        simple_moving_average([1, 2, 3], 0)
