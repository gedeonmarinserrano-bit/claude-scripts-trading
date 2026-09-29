"""Tres estrategias tendenciales (solo largos) con un backtest sencillo.

Estrategias:
    - ma_crossover:       cruce EMA rápida/lenta + filtro SMA 200 + stop ATR.
    - donchian_breakout:  ruptura de canal Donchian (tipo Turtle).
    - supertrend_adx:     Supertrend filtrado por ADX + Chandelier Exit.

Cada estrategia devuelve una lista de posiciones (1 = largo, 0 = fuera),
calculada con datos hasta el cierre de cada barra. El backtest aplica la
posición de la barra i al retorno de i a i+1, así que no hay lookahead.

Uso:
    python -m scripts.trend_strategies datos.csv --strategy donchian
    python -m scripts.trend_strategies --demo

El CSV debe tener columnas high, low y close (date/open son opcionales).
Solo usa la librería estándar.
"""

import argparse
import csv
import math
import random


# --------------------------------------------------------------------------
# Indicadores. Todos devuelven listas alineadas con la entrada, con None
# donde aún no hay datos suficientes.
# --------------------------------------------------------------------------

def sma(values, window):
    if window <= 0:
        raise ValueError("window must be positive")
    out = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= window:
            total -= values[i - window]
        if i >= window - 1:
            out[i] = total / window
    return out


def ema(values, window):
    if window <= 0:
        raise ValueError("window must be positive")
    out = [None] * len(values)
    if len(values) < window:
        return out
    alpha = 2 / (window + 1)
    out[window - 1] = sum(values[:window]) / window
    for i in range(window, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def rma(values, window):
    """Media suavizada de Wilder. Ignora los None iniciales."""
    out = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None or len(values) - start < window:
        return out
    first = start + window - 1
    out[first] = sum(values[start:first + 1]) / window
    for i in range(first + 1, len(values)):
        out[i] = (out[i - 1] * (window - 1) + values[i]) / window
    return out


def true_range(high, low, close):
    tr = [high[0] - low[0]]
    for i in range(1, len(close)):
        tr.append(max(high[i] - low[i],
                      abs(high[i] - close[i - 1]),
                      abs(low[i] - close[i - 1])))
    return tr


def atr(high, low, close, window=14):
    return rma(true_range(high, low, close), window)


def adx(high, low, close, window=14):
    n = len(close)
    plus_dm = [None] + [0.0] * (n - 1)
    minus_dm = [None] + [0.0] * (n - 1)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down
    tr = [None] + true_range(high, low, close)[1:]
    s_tr, s_plus, s_minus = rma(tr, window), rma(plus_dm, window), rma(minus_dm, window)
    dx = [None] * n
    for i in range(n):
        if s_tr[i] is None or s_tr[i] == 0:
            continue
        plus_di = 100 * s_plus[i] / s_tr[i]
        minus_di = 100 * s_minus[i] / s_tr[i]
        di_sum = plus_di + minus_di
        dx[i] = 0.0 if di_sum == 0 else 100 * abs(plus_di - minus_di) / di_sum
    return rma(dx, window)


def rolling_max(values, window):
    return [max(values[i - window + 1:i + 1]) if i >= window - 1 else None
            for i in range(len(values))]


def rolling_min(values, window):
    return [min(values[i - window + 1:i + 1]) if i >= window - 1 else None
            for i in range(len(values))]


def supertrend(high, low, close, window=10, multiplier=3.0):
    """Devuelve (línea, dirección) con dirección 1 alcista / -1 bajista."""
    n = len(close)
    atr_values = atr(high, low, close, window)
    line, direction = [None] * n, [None] * n
    upper = lower = None
    for i in range(n):
        if atr_values[i] is None:
            continue
        hl2 = (high[i] + low[i]) / 2
        basic_upper = hl2 + multiplier * atr_values[i]
        basic_lower = hl2 - multiplier * atr_values[i]
        if upper is None:
            upper, lower, d = basic_upper, basic_lower, 1
        else:
            if basic_upper < upper or close[i - 1] > upper:
                upper = basic_upper
            if basic_lower > lower or close[i - 1] < lower:
                lower = basic_lower
            d = direction[i - 1]
            if d == 1 and close[i] < lower:
                d = -1
            elif d == -1 and close[i] > upper:
                d = 1
        direction[i] = d
        line[i] = lower if d == 1 else upper
    return line, direction


# --------------------------------------------------------------------------
# Estrategias
# --------------------------------------------------------------------------

def ma_crossover(high, low, close, fast=20, slow=50, trend=200,
                 atr_window=14, atr_mult=3.0):
    """Largo cuando EMA rápida > EMA lenta y close > SMA de tendencia.

    Sale en el cruce contrario o si el close perfora un stop dinámico
    (máximo close desde la entrada - atr_mult * ATR).
    """
    ema_fast, ema_slow = ema(close, fast), ema(close, slow)
    sma_trend, atr_values = sma(close, trend), atr(high, low, close, atr_window)
    # Condición alcista completa. Se entra cuando pasa a ser cierta (el cruce
    # o la recuperación de la SMA de tendencia, lo que ocurra último); tras
    # un stop no se reentra hasta que la condición se reinicie.
    bullish = [None not in (f, s, t) and f > s and c > t
               for f, s, t, c in zip(ema_fast, ema_slow, sma_trend, close)]
    positions = [0] * len(close)
    in_position, peak = False, None
    for i in range(1, len(close)):
        if None in (ema_fast[i], ema_slow[i], sma_trend[i], atr_values[i]):
            continue
        if in_position:
            peak = max(peak, close[i])
            stop = peak - atr_mult * atr_values[i]
            if ema_fast[i] < ema_slow[i] or close[i] < stop:
                in_position = False
        elif bullish[i] and not bullish[i - 1]:
            in_position, peak = True, close[i]
        positions[i] = 1 if in_position else 0
    return positions


def donchian_breakout(high, low, close, entry=20, exit=10):
    """Largo si el close supera el máximo de las `entry` barras previas;
    sale si cae por debajo del mínimo de las `exit` barras previas."""
    upper, lower = rolling_max(high, entry), rolling_min(low, exit)
    positions = [0] * len(close)
    in_position = False
    for i in range(1, len(close)):
        if in_position:
            if lower[i - 1] is not None and close[i] < lower[i - 1]:
                in_position = False
        elif upper[i - 1] is not None and close[i] > upper[i - 1]:
            in_position = True
        positions[i] = 1 if in_position else 0
    return positions


def supertrend_adx(high, low, close, st_window=10, st_mult=3.0,
                   adx_window=14, adx_threshold=25.0,
                   chandelier_window=22, chandelier_mult=3.0):
    """Largo si el Supertrend es alcista y el ADX > umbral y subiendo.

    Sale si el Supertrend gira a bajista o el close perfora el Chandelier
    Exit (máximo de `chandelier_window` barras - chandelier_mult * ATR).
    """
    _, direction = supertrend(high, low, close, st_window, st_mult)
    adx_values = adx(high, low, close, adx_window)
    atr_values = atr(high, low, close, chandelier_window)
    highest = rolling_max(high, chandelier_window)
    positions = [0] * len(close)
    in_position = False
    for i in range(1, len(close)):
        if direction[i] is None:
            continue
        if in_position:
            chandelier = (highest[i] - chandelier_mult * atr_values[i]
                          if atr_values[i] is not None and highest[i] is not None
                          else None)
            if direction[i] == -1 or (chandelier is not None and close[i] < chandelier):
                in_position = False
        elif (direction[i] == 1 and adx_values[i] is not None
              and adx_values[i - 1] is not None
              and adx_values[i] > adx_threshold
              and adx_values[i] > adx_values[i - 1]):
            in_position = True
        positions[i] = 1 if in_position else 0
    return positions


STRATEGIES = {
    "ma_crossover": ma_crossover,
    "donchian": donchian_breakout,
    "supertrend_adx": supertrend_adx,
}


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

def backtest(close, positions, cost=0.001, periods_per_year=252):
    """Backtest de una posición 1/0 sobre precios de cierre.

    `cost` es la comisión + slippage por lado, como fracción del precio.
    """
    if len(close) != len(positions):
        raise ValueError("close and positions must have the same length")
    equity = [1.0]
    trades, entry_equity, prev = [], None, 0
    for i in range(len(close) - 1):
        pos = positions[i]
        value = equity[-1]
        if pos != prev:
            value *= 1 - cost
            if pos == 1:
                entry_equity = value
            else:
                trades.append(value / entry_equity - 1)
        value *= 1 + pos * (close[i + 1] / close[i] - 1)
        equity.append(value)
        prev = pos
    if prev == 1:
        equity[-1] *= 1 - cost
        trades.append(equity[-1] / entry_equity - 1)

    peak, max_dd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, 1 - v / peak)

    years = (len(equity) - 1) / periods_per_year
    total_return = equity[-1] - 1
    cagr = equity[-1] ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else 0.0
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "exposure": sum(positions[:-1]) / max(len(positions) - 1, 1),
        "equity": equity,
    }


# --------------------------------------------------------------------------
# Datos y CLI
# --------------------------------------------------------------------------

def load_csv(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fields = {name.strip().lower(): name for name in reader.fieldnames or []}
        missing = {"high", "low", "close"} - fields.keys()
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")
        high, low, close = [], [], []
        for row in reader:
            high.append(float(row[fields["high"]]))
            low.append(float(row[fields["low"]]))
            close.append(float(row[fields["close"]]))
    return high, low, close


def synthetic_data(n=2000, seed=42):
    """Paseo aleatorio con regímenes de tendencia, para probar sin datos."""
    rng = random.Random(seed)
    high, low, close = [], [], []
    price, drift = 100.0, 0.0
    for i in range(n):
        if i % 150 == 0:
            drift = rng.choice([-0.002, 0.0, 0.0015, 0.003])
        new_price = price * math.exp(drift + rng.gauss(0, 0.012))
        spread = abs(rng.gauss(0, 0.006)) * new_price
        high.append(max(price, new_price) + spread)
        low.append(min(price, new_price) - spread)
        close.append(new_price)
        price = new_price
    return high, low, close


def format_report(name, stats):
    return (f"{name:<16} ret {stats['total_return']:>8.1%}  "
            f"CAGR {stats['cagr']:>6.1%}  maxDD {stats['max_drawdown']:>6.1%}  "
            f"trades {stats['trades']:>4}  win {stats['win_rate']:>5.1%}  "
            f"expo {stats['exposure']:>5.1%}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="?", help="CSV con columnas high, low, close")
    parser.add_argument("--demo", action="store_true", help="usar datos sintéticos")
    parser.add_argument("--strategy", choices=["all", *STRATEGIES], default="all")
    parser.add_argument("--cost", type=float, default=0.001,
                        help="coste por lado (comisión + slippage), por defecto 0.001")
    parser.add_argument("--periods-per-year", type=int, default=252)
    args = parser.parse_args(argv)

    if args.demo:
        high, low, close = synthetic_data()
    elif args.csv:
        high, low, close = load_csv(args.csv)
    else:
        parser.error("indica un CSV o usa --demo")

    names = STRATEGIES if args.strategy == "all" else [args.strategy]
    bh = backtest(close, [1] * len(close), args.cost, args.periods_per_year)
    print(format_report("buy_and_hold", bh))
    for name in names:
        positions = STRATEGIES[name](high, low, close)
        print(format_report(name, backtest(close, positions, args.cost,
                                           args.periods_per_year)))


if __name__ == "__main__":
    main()
