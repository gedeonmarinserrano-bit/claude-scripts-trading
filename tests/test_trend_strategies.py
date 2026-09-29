import pytest

from scripts.trend_strategies import (
    STRATEGIES,
    adx,
    atr,
    backtest,
    donchian_breakout,
    ema,
    load_csv,
    main,
    sma,
    supertrend,
    synthetic_data,
)


def test_sma_aligned_with_input():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_rejects_bad_window():
    with pytest.raises(ValueError):
        sma([1, 2], 0)


def test_ema_seeds_with_sma():
    out = ema([1, 2, 3, 4], 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0
    assert out[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)


def test_atr_constant_range():
    high, low, close = [11.0] * 30, [9.0] * 30, [10.0] * 30
    values = atr(high, low, close, 14)
    assert values[12] is None
    assert values[-1] == pytest.approx(2.0)


def test_adx_high_in_steady_uptrend():
    close = [100 + i for i in range(80)]
    high = [c + 0.5 for c in close]
    low = [c - 0.5 for c in close]
    assert adx(high, low, close, 14)[-1] > 90


def test_supertrend_bullish_in_uptrend():
    close = [100 + i for i in range(60)]
    high = [c + 1 for c in close]
    low = [c - 1 for c in close]
    line, direction = supertrend(high, low, close)
    assert direction[-1] == 1
    assert line[-1] < close[-1]


def test_donchian_enters_on_breakout_and_exits_on_breakdown():
    close = [10.0] * 25 + [12.0, 13.0, 14.0] + [8.0, 8.0]
    high = [c + 0.1 for c in close]
    low = [c - 0.1 for c in close]
    positions = donchian_breakout(high, low, close, entry=20, exit=10)
    assert positions[24] == 0
    assert positions[25] == 1
    assert positions[28] == 0


def test_backtest_buy_and_hold_without_costs():
    close = [100.0, 110.0, 121.0]
    stats = backtest(close, [1, 1, 1], cost=0)
    assert stats["total_return"] == pytest.approx(0.21)
    assert stats["trades"] == 1
    assert stats["max_drawdown"] == 0


def test_backtest_applies_position_to_next_bar():
    close = [100.0, 50.0, 100.0]
    # Entrar al cierre de la barra 1 solo captura la subida de 50 a 100.
    stats = backtest(close, [0, 1, 1], cost=0)
    assert stats["total_return"] == pytest.approx(1.0)


def test_backtest_charges_costs_per_side():
    stats = backtest([100.0, 100.0], [1, 1], cost=0.01)
    assert stats["total_return"] == pytest.approx(0.99 * 0.99 - 1)


def test_backtest_drawdown():
    stats = backtest([100.0, 50.0, 75.0], [1, 1, 1], cost=0)
    assert stats["max_drawdown"] == pytest.approx(0.5)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategies_produce_valid_positions(name):
    high, low, close = synthetic_data(n=600, seed=1)
    positions = STRATEGIES[name](high, low, close)
    assert len(positions) == len(close)
    assert set(positions) <= {0, 1}
    assert 1 in positions


def test_load_csv_and_cli(tmp_path, capsys):
    high, low, close = synthetic_data(n=300, seed=3)
    path = tmp_path / "data.csv"
    lines = ["Date,Open,High,Low,Close"]
    lines += [f"d{i},{c},{h},{l},{c}" for i, (h, l, c) in enumerate(zip(high, low, close))]
    path.write_text("\n".join(lines))
    loaded = load_csv(path)
    assert loaded[2] == pytest.approx(close)
    main([str(path), "--strategy", "donchian"])
    out = capsys.readouterr().out
    assert "buy_and_hold" in out and "donchian" in out


def test_load_csv_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,close\n1,10\n")
    with pytest.raises(ValueError, match="high"):
        load_csv(path)
