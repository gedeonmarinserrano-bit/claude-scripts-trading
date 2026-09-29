import math

import pytest

from scripts.trend_strategies import (
    STRATEGIES,
    adx,
    atr,
    atr_position_sizing,
    backtest,
    donchian_breakout,
    ema,
    load_csv,
    main,
    sma,
    supertrend,
    synthetic_data,
    walk_forward,
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


def _mirror(high, low, close):
    """Serie invertida (precio -> 1/precio): una tendencia alcista pasa a bajista."""
    return ([1 / l for l in low], [1 / h for h in high], [1 / c for c in close])


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_long_only_by_default(name):
    high, low, close = synthetic_data(n=600, seed=1)
    assert -1 not in STRATEGIES[name](high, low, close)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_shorts_in_downtrend(name):
    # Tendencia bajista con oscilaciones (una serie perfecta satura el ADX en 100).
    close = [100 * 0.995 ** i * (1 + 0.01 * math.sin(i)) for i in range(400)]
    high = [c * 1.004 for c in close]
    low = [c * 0.996 for c in close]
    assert set(STRATEGIES[name](high, low, close)) == {0}
    assert -1 in STRATEGIES[name](high, low, close, allow_short=True)


def test_donchian_short_mirrors_long():
    close = [10.0] * 25 + [12.0, 13.0, 14.0] + [8.0, 8.0]
    high = [c + 0.1 for c in close]
    low = [c - 0.1 for c in close]
    longs = donchian_breakout(high, low, close, entry=20, exit=10, allow_short=True)
    shorts = donchian_breakout(*_mirror(high, low, close), entry=20, exit=10,
                               allow_short=True)
    assert shorts == [-p for p in longs]


def test_backtest_short_profits_when_price_falls():
    stats = backtest([100.0, 90.0, 81.0], [-1, -1, -1], cost=0)
    assert stats["total_return"] == pytest.approx(1.1 * 1.1 - 1)
    assert stats["trades"] == 1


def test_backtest_flip_counts_two_trades_and_costs():
    stats = backtest([100.0, 100.0, 100.0], [1, -1, -1], cost=0.01)
    assert stats["trades"] == 2
    assert stats["total_return"] == pytest.approx(0.99 ** 4 - 1)


def test_backtest_fractional_position():
    stats = backtest([100.0, 110.0], [0.5, 0.5], cost=0)
    assert stats["total_return"] == pytest.approx(0.05)
    assert stats["exposure"] == pytest.approx(0.5)


def test_atr_sizing_risks_fixed_fraction():
    n = 40
    close = [100.0] * n
    high, low = [101.0] * n, [99.0] * n  # ATR = 2
    signals = [0] * 30 + [1] * 5 + [-1] * 5
    sized = atr_position_sizing(signals, high, low, close, risk=0.01,
                                atr_window=20, stop_mult=2.0, max_leverage=5)
    # 0.01 * 100 / (2 * 2) = 0.25
    assert sized[:30] == [0.0] * 30
    assert sized[30:35] == [pytest.approx(0.25)] * 5
    assert sized[35:] == [pytest.approx(-0.25)] * 5


def test_atr_sizing_respects_max_leverage_and_missing_atr():
    close = [100.0] * 30
    high, low = [100.1] * 30, [99.9] * 30
    sized = atr_position_sizing([1] * 30, high, low, close, atr_window=20,
                                max_leverage=1.0)
    assert sized == [0.0] * 30  # entra antes de que haya ATR
    sized = atr_position_sizing([0] * 25 + [1] * 5, high, low, close,
                                atr_window=20, max_leverage=1.0)
    assert sized[-1] == 1.0


def test_walk_forward_folds_and_params():
    high, low, close = synthetic_data(n=1000, seed=5)
    result = walk_forward(high, low, close, "donchian", train=500, test=200)
    assert [(f["start"], f["end"]) for f in result["folds"]] == [
        (500, 700), (700, 900), (900, 1000)]
    for fold in result["folds"]:
        assert fold["params"]["entry"] in (20, 55, 100)
    assert result["positions"][:500] == [0.0] * 500


def test_walk_forward_has_no_lookahead():
    high, low, close = synthetic_data(n=1000, seed=5)
    base = walk_forward(high, low, close, "supertrend_adx", train=500, test=200,
                        allow_short=True, sizing={"risk": 0.01})
    # Alterar el futuro no puede cambiar las posiciones del pasado.
    close2 = close[:800] + [c * 3 for c in close[800:]]
    high2 = high[:800] + [h * 3 for h in high[800:]]
    low2 = low[:800] + [x * 3 for x in low[800:]]
    changed = walk_forward(high2, low2, close2, "supertrend_adx", train=500,
                           test=200, allow_short=True, sizing={"risk": 0.01})
    assert changed["positions"][:800] == base["positions"][:800]


def test_walk_forward_needs_enough_data():
    high, low, close = synthetic_data(n=300, seed=5)
    with pytest.raises(ValueError):
        walk_forward(high, low, close, "donchian", train=250, test=100)


def test_cli_short_sizing_and_walk_forward(capsys):
    main(["--demo", "--strategy", "donchian", "--short", "--risk", "0.01",
          "--walk-forward", "--train", "1000", "--test", "500"])
    out = capsys.readouterr().out
    assert "Fuera de muestra" in out and "entry=" in out
