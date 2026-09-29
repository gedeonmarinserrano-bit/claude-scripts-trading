import pytest

from ctrader_mcp.convert import (
    lots_to_volume, normalize_symbol, pips_to_relative, position_summary, trendbar_to_ohlc, volume_to_lots,
)


def test_trendbar_to_ohlc():
    bar = {"low": 108000, "deltaOpen": 20, "deltaHigh": 55, "deltaClose": 30,
           "volume": 1234, "utcTimestampInMinutes": 28_000_000}
    ohlc = trendbar_to_ohlc(bar)
    assert ohlc == {"time": "2023-03-28T10:40:00+00:00", "open": 1.0802, "high": 1.08055,
                    "low": 1.08, "close": 1.0803, "volume": 1234}


def test_lots_to_volume_rounds_to_step():
    assert lots_to_volume(0.1, 10_000_000) == 1_000_000
    assert lots_to_volume(0.123, 10_000_000, step_volume=100_000) == 1_200_000


def test_lots_to_volume_limits():
    with pytest.raises(ValueError):
        lots_to_volume(0, 10_000_000)
    with pytest.raises(ValueError):
        lots_to_volume(0.001, 10_000_000, min_volume=100_000)
    with pytest.raises(ValueError):
        lots_to_volume(100, 10_000_000, max_volume=10_000_000)


def test_volume_to_lots():
    assert volume_to_lots(1_000_000, 10_000_000) == 0.1


def test_pips_to_relative():
    assert pips_to_relative(20, 4) == 200
    assert pips_to_relative(15, 2) == 15_000


def test_normalize_symbol():
    assert normalize_symbol("eur/usd") == normalize_symbol("EURUSD") == "EURUSD"


def test_position_summary():
    position = {"positionId": 7, "price": 1.1, "swap": -150, "moneyDigits": 2,
                "tradeData": {"symbolId": 1, "volume": 1_000_000, "tradeSide": 1, "openTimestamp": 0}}
    summary = position_summary(position, symbol_names={1: "EURUSD"})
    assert summary["symbol"] == "EURUSD"
    assert summary["side"] == "BUY"
    assert summary["units"] == 10_000
    assert summary["swap"] == -1.5
    assert summary["openTime"] == "1970-01-01T00:00:00+00:00"
