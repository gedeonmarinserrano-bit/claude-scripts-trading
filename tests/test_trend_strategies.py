import math

import pytest

import datetime

from scripts.trend_strategies import (
    STRATEGIES,
    adx,
    align_assets,
    apply_sizing,
    atr,
    atr_position_sizing,
    backtest,
    backtest_portfolio,
    donchian_breakout,
    ema,
    load_csv,
    load_csv_dated,
    main,
    portfolio_vol_target,
    run_portfolio,
    sma,
    supertrend,
    synthetic_data,
    trend_ensemble,
    volatility_target,
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
    assert all(0 <= p <= 1 for p in positions)
    assert any(p > 0 for p in positions)


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


def test_load_csv_missing_close(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,high,low\n1,10,9\n")
    with pytest.raises(ValueError, match="close"):
        load_csv(path)


def test_load_csv_close_only_and_bad_rows(tmp_path):
    path = tmp_path / "wti.csv"
    path.write_text("DATE,Close\n2020-01-02,10\n2020-01-03,.\n2020-01-06,11\n")
    assert load_csv(path) == ([10.0, 11.0], [10.0, 11.0], [10.0, 11.0])


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


def test_cash_interest_on_idle_capital():
    close = [100.0] * 253
    stats = backtest(close, [0] * 253, cost=0, cash_rate=0.05)
    assert stats["total_return"] == pytest.approx(0.05)
    # Invertido al 100 % no cobra intereses.
    assert backtest(close, [1] * 253, cost=0, cash_rate=0.05)["total_return"] == \
        pytest.approx(0)


def test_cash_interest_partial_short_and_leverage():
    close = [100.0] * 253
    half = backtest(close, [0.5] * 253, cost=0, cash_rate=0.05)["total_return"]
    assert half == pytest.approx(1.05 ** 0.5 - 1, rel=1e-3)
    short = backtest(close, [-1] * 253, cost=0, cash_rate=0.05)["total_return"]
    assert short == pytest.approx(0.05)
    levered = backtest(close, [2] * 253, cost=0, cash_rate=0.05)["total_return"]
    assert levered < -0.04  # paga financiación por el 100 % extra


def test_sharpe_is_in_excess_of_cash_rate():
    close = [100.0] * 300
    assert backtest(close, [0] * 300, cost=0, cash_rate=0.05)["sharpe"] == 0.0


def test_portfolio_matches_single_asset():
    high, low, close = synthetic_data(n=400, seed=2)
    positions = donchian_breakout(high, low, close)
    single = backtest(close, positions, cost=0.001, cash_rate=0.02)
    combo = backtest_portfolio([close], [positions], cost=0.001, cash_rate=0.02)
    assert combo["total_return"] == pytest.approx(single["total_return"], rel=1e-6)
    assert combo["max_drawdown"] == pytest.approx(single["max_drawdown"], rel=1e-6)


def test_portfolio_equal_weights():
    a = [100.0, 110.0]
    b = [100.0, 90.0]
    stats = backtest_portfolio([a, b], [[0.5, 0.5], [0.5, 0.5]], cost=0)
    assert stats["total_return"] == pytest.approx(0.0)
    assert stats["exposure"] == pytest.approx(1.0)
    assert stats["trades"] == 2


def test_portfolio_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        backtest_portfolio([[1.0, 2.0]], [[1, 1, 1]])


def test_align_assets_uses_common_dates():
    d = [datetime.date(2020, 1, i) for i in range(1, 6)]
    assets = {
        "a": (d, [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5]),
        "b": ([d[0], d[2], d[4]], [10, 30, 50], [10, 30, 50], [10, 30, 50]),
    }
    dates, aligned = align_assets(assets)
    assert dates == [d[0], d[2], d[4]]
    assert aligned["a"][2] == [1, 3, 5]
    assert aligned["b"][2] == [10, 30, 50]


def test_load_csv_dated_detects_format_and_sorts(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("Date,High,Low,Close\n1/13/2020,3,1,2\n1/2/2020,5,3,4\n")
    dates, high, low, close = load_csv_dated(path)
    assert dates == [datetime.date(2020, 1, 2), datetime.date(2020, 1, 13)]
    assert close == [4.0, 2.0]


def test_load_csv_dated_requires_dates(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("close\n1\n2\n")
    with pytest.raises(ValueError, match="date"):
        load_csv_dated(path)


def test_run_portfolio_weights_and_walk_forward():
    assets = {f"s{k}": synthetic_data(n=900, seed=k) for k in range(3)}
    plain = run_portfolio(assets, "donchian")
    for data in plain["assets"].values():
        assert set(data["positions"]) <= {0, 1 / 3}
    wf = run_portfolio(assets, "donchian", sizing={"risk": 0.01},
                       walk_forward_args={"train": 500, "test": 200})
    assert len(wf["stats"]["equity"]) == 400
    assert all(p == 0 for d in wf["assets"].values() for p in d["positions"][:500])


def _write_asset(path, seed, start=0):
    high, low, close = synthetic_data(n=600, seed=seed)
    base = datetime.date(2000, 1, 3)
    lines = ["Date,High,Low,Close"]
    for i, (h, l, c) in enumerate(zip(high, low, close)):
        lines.append(f"{base + datetime.timedelta(days=i + start)},{h},{l},{c}")
    path.write_text("\n".join(lines))


def test_cli_portfolio(tmp_path, capsys):
    _write_asset(tmp_path / "uno.csv", 1)
    _write_asset(tmp_path / "dos.csv", 2, start=10)
    main([str(tmp_path / "uno.csv"), str(tmp_path / "dos.csv"),
          "--strategy", "supertrend_adx", "--cash-rate", "0.02"])
    out = capsys.readouterr().out
    assert "Cartera de 2 activos: uno, dos" in out
    assert "590 barras" in out
    assert "supertrend_adx" in out and "    uno" in out


def test_trend_ensemble_is_vote_average():
    # Sube 300 barras y luego baja: al principio del giro solo los pares
    # rápidos se dan la vuelta, así que la posición baja por escalones.
    close = [100 + i for i in range(300)] + [400 - 2 * i for i in range(1, 120)]
    positions = trend_ensemble(close, close, close)
    assert positions[299] == 1.0
    assert set(positions[300:]) >= {0.75, 0.5}
    assert positions[-1] == 0.0
    shorts = trend_ensemble(close, close, close, allow_short=True)
    assert shorts[-1] == -1.0


def test_trend_ensemble_waits_for_slowest_average():
    close = [100 + i for i in range(300)]
    positions = trend_ensemble(close, close, close)
    assert positions[254] == 0.0
    assert positions[255] == 1.0


def test_volatility_target_scales_to_target():
    rng = __import__("random").Random(0)
    close = [100.0]
    for _ in range(1500):
        close.append(close[-1] * math.exp(rng.gauss(0, 0.02)))  # ~32 % anual
    sized = volatility_target([1.0] * len(close), close, target_vol=0.16,
                              span=32, max_leverage=2.0, buffer=0.0)
    assert sized[:32] == [0.0] * 32
    average = sum(sized[100:]) / len(sized[100:])
    assert average == pytest.approx(0.5, rel=0.15)


def test_volatility_target_caps_leverage_and_buffers():
    close = [100 * (1.0001 if i % 2 else 0.9999) ** i for i in range(200)]
    sized = volatility_target([1.0] * 200, close, target_vol=0.5, max_leverage=1.5)
    assert max(sized) == 1.5
    signal = [1.0] * 100 + [0.0] * 100
    sized = volatility_target(signal, close, target_vol=0.5, max_leverage=1.5)
    assert sized[-1] == 0.0


def test_volatility_target_buffer_limits_rebalancing():
    rng = __import__("random").Random(1)
    close = [100.0]
    for _ in range(600):
        close.append(close[-1] * math.exp(rng.gauss(0, 0.01)))
    tight = volatility_target([1.0] * len(close), close, buffer=0.0)
    loose = volatility_target([1.0] * len(close), close, buffer=0.1)
    changes = lambda xs: sum(1 for a, b in zip(xs, xs[1:]) if a != b)
    assert changes(loose) < changes(tight) / 5


def test_apply_sizing_dispatch():
    high, low, close = synthetic_data(n=300, seed=4)
    signal = [1] * 300
    assert apply_sizing(signal, high, low, close, None) is signal
    by_vol = apply_sizing(signal, high, low, close, {"target_vol": 0.1})
    by_atr = apply_sizing([0] + [1] * 299, high, low, close, {"risk": 0.01})
    assert by_vol == volatility_target(signal, close, target_vol=0.1)
    assert len(set(by_atr[1:])) == 1


def test_cli_vol_target_and_exclusive_sizing(capsys):
    main(["--demo", "--strategy", "trend_ensemble", "--vol-target", "0.15"])
    assert "trend_ensemble" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--demo", "--risk", "0.01", "--vol-target", "0.15"])


def _random_walk(seed, n=800, sigma=0.01):
    rng = __import__("random").Random(seed)
    close = [100.0]
    for _ in range(n - 1):
        close.append(close[-1] * math.exp(rng.gauss(0, sigma)))
    return close


def test_portfolio_vol_target_hits_target_with_room():
    closes = [_random_walk(1), _random_walk(2)]  # ~16 % anual cada uno, independientes
    weights = [[0.5] * 800, [0.5] * 800]
    scaled = portfolio_vol_target(closes, weights, target_vol=0.10, max_gross=10,
                                  buffer=0.0)
    assert scaled[0][:32] == [0.0] * 32
    # Vol de la cartera 50/50 ~ 16 % / sqrt(2) ~ 11 %: el factor ronda 0.9.
    gross = [scaled[0][i] + scaled[1][i] for i in range(100, 800)]
    assert sum(gross) / len(gross) == pytest.approx(0.1 / (0.01 * math.sqrt(252) / math.sqrt(2)),
                                                    rel=0.15)


def test_portfolio_vol_target_respects_max_gross_and_zero():
    closes = [_random_walk(3), _random_walk(4)]
    weights = [[0.25] * 800, [-0.25] * 800]
    scaled = portfolio_vol_target(closes, weights, target_vol=1.0, max_gross=1.5,
                                  buffer=0.0)
    assert max(abs(a) + abs(b) for a, b in zip(*scaled)) == pytest.approx(1.5)
    assert all(a <= 0 for a in scaled[1])
    zero = portfolio_vol_target(closes, [[0.0] * 800] * 2)
    assert zero == [[0.0] * 800] * 2


def test_portfolio_vol_target_has_no_lookahead():
    closes = [_random_walk(5), _random_walk(6)]
    weights = [[0.5] * 800, [0.5] * 800]
    base = portfolio_vol_target(closes, weights)
    changed = [c[:500] + [x * 2 for x in c[500:]] for c in closes]
    moved = portfolio_vol_target(changed, weights)
    assert [w[:500] for w in moved] == [w[:500] for w in base]


def test_run_portfolio_with_portfolio_vol():
    assets = {f"s{k}": synthetic_data(n=600, seed=k) for k in range(3)}
    result = run_portfolio(assets, "trend_ensemble", sizing={"target_vol": 0.15},
                           portfolio_vol={"target_vol": 0.10, "max_gross": 1.0})
    gross = [sum(abs(d["positions"][i]) for d in result["assets"].values())
             for i in range(600)]
    assert max(gross) <= 1.0 + 1e-9
    assert max(gross) > 0


def test_cli_portfolio_vol(tmp_path, capsys):
    _write_asset(tmp_path / "uno.csv", 1)
    _write_asset(tmp_path / "dos.csv", 2)
    main([str(tmp_path / "uno.csv"), str(tmp_path / "dos.csv"), "--strategy",
          "trend_ensemble", "--vol-target", "0.15", "--portfolio-vol", "0.10"])
    assert "trend_ensemble" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--demo", "--portfolio-vol", "0.10"])
