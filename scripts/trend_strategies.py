"""Tres estrategias tendenciales con backtest, sizing por ATR y walk-forward.

Estrategias (solo largos por defecto; --short activa los cortos):
    - ma_crossover:       cruce EMA rápida/lenta + filtro SMA 200 + stop ATR.
    - donchian_breakout:  ruptura de canal Donchian (tipo Turtle).
    - supertrend_adx:     Supertrend filtrado por ADX + Chandelier Exit.

Cada estrategia devuelve una lista de posiciones (1 = largo, -1 = corto,
0 = fuera), calculada con datos hasta el cierre de cada barra. El backtest
aplica la posición de la barra i al retorno de i a i+1, así que no hay
lookahead.

Uso:
    python -m scripts.trend_strategies datos.csv --strategy donchian
    python -m scripts.trend_strategies --demo --short --risk 0.01
    python -m scripts.trend_strategies --demo --walk-forward

El CSV debe tener columnas high, low y close (date/open son opcionales).
Solo usa la librería estándar.
"""

import argparse
import csv
import itertools
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
# Estrategias. Devuelven posiciones -1 (corto), 0 (fuera) o 1 (largo).
# Con allow_short=False (por defecto) solo operan en largo.
# --------------------------------------------------------------------------

def ma_crossover(high, low, close, fast=20, slow=50, trend=200,
                 atr_window=14, atr_mult=3.0, allow_short=False):
    """Largo cuando EMA rápida > EMA lenta y close > SMA de tendencia.

    Sale en el cruce contrario o si el close perfora un stop dinámico
    (máximo close desde la entrada - atr_mult * ATR). Los cortos son
    simétricos: EMA rápida < lenta y close < SMA de tendencia.
    """
    ema_fast, ema_slow = ema(close, fast), ema(close, slow)
    sma_trend, atr_values = sma(close, trend), atr(high, low, close, atr_window)
    # Se entra cuando la condición completa pasa a ser cierta (el cruce o la
    # recuperación de la SMA de tendencia, lo que ocurra último); tras un
    # stop no se reentra hasta que la condición se reinicie.
    ready = [None not in (f, s, t) for f, s, t in zip(ema_fast, ema_slow, sma_trend)]
    bullish = [r and f > s and c > t
               for r, f, s, t, c in zip(ready, ema_fast, ema_slow, sma_trend, close)]
    bearish = [r and f < s and c < t
               for r, f, s, t, c in zip(ready, ema_fast, ema_slow, sma_trend, close)]
    positions = [0] * len(close)
    pos, extreme = 0, None
    for i in range(1, len(close)):
        if not ready[i] or atr_values[i] is None:
            continue
        if pos == 1:
            extreme = max(extreme, close[i])
            if ema_fast[i] < ema_slow[i] or close[i] < extreme - atr_mult * atr_values[i]:
                pos = 0
        elif pos == -1:
            extreme = min(extreme, close[i])
            if ema_fast[i] > ema_slow[i] or close[i] > extreme + atr_mult * atr_values[i]:
                pos = 0
        if pos == 0:
            if bullish[i] and not bullish[i - 1]:
                pos, extreme = 1, close[i]
            elif allow_short and bearish[i] and not bearish[i - 1]:
                pos, extreme = -1, close[i]
        positions[i] = pos
    return positions


def donchian_breakout(high, low, close, entry=20, exit=10, allow_short=False):
    """Largo si el close supera el máximo de las `entry` barras previas;
    sale si cae por debajo del mínimo de las `exit` barras previas.
    Los cortos son el espejo (romper el mínimo, salir en el máximo)."""
    entry_high, entry_low = rolling_max(high, entry), rolling_min(low, entry)
    exit_high, exit_low = rolling_max(high, exit), rolling_min(low, exit)
    positions = [0] * len(close)
    pos = 0
    for i in range(1, len(close)):
        if pos == 1 and exit_low[i - 1] is not None and close[i] < exit_low[i - 1]:
            pos = 0
        elif pos == -1 and exit_high[i - 1] is not None and close[i] > exit_high[i - 1]:
            pos = 0
        if pos == 0 and entry_high[i - 1] is not None:
            if close[i] > entry_high[i - 1]:
                pos = 1
            elif allow_short and close[i] < entry_low[i - 1]:
                pos = -1
        positions[i] = pos
    return positions


def supertrend_adx(high, low, close, st_window=10, st_mult=3.0,
                   adx_window=14, adx_threshold=25.0,
                   chandelier_window=22, chandelier_mult=3.0, allow_short=False):
    """Entra en la dirección del Supertrend si el ADX > umbral y subiendo.

    Sale si el Supertrend gira o el close perfora el Chandelier Exit
    (largos: máximo de `chandelier_window` barras - chandelier_mult * ATR;
    cortos: mínimo + chandelier_mult * ATR).
    """
    _, direction = supertrend(high, low, close, st_window, st_mult)
    adx_values = adx(high, low, close, adx_window)
    atr_values = atr(high, low, close, chandelier_window)
    highest = rolling_max(high, chandelier_window)
    lowest = rolling_min(low, chandelier_window)
    positions = [0] * len(close)
    pos = 0
    for i in range(1, len(close)):
        if direction[i] is None:
            continue
        stop_ready = atr_values[i] is not None and highest[i] is not None
        if pos == 1:
            if direction[i] == -1 or (
                    stop_ready and close[i] < highest[i] - chandelier_mult * atr_values[i]):
                pos = 0
        elif pos == -1:
            if direction[i] == 1 or (
                    stop_ready and close[i] > lowest[i] + chandelier_mult * atr_values[i]):
                pos = 0
        strong = (adx_values[i] is not None and adx_values[i - 1] is not None
                  and adx_values[i] > adx_threshold
                  and adx_values[i] > adx_values[i - 1])
        if pos == 0 and strong:
            if direction[i] == 1:
                pos = 1
            elif allow_short and direction[i] == -1:
                pos = -1
        positions[i] = pos
    return positions


STRATEGIES = {
    "ma_crossover": ma_crossover,
    "donchian": donchian_breakout,
    "supertrend_adx": supertrend_adx,
}

# Rejillas de parámetros que prueba el walk-forward.
PARAM_GRIDS = {
    "ma_crossover": {"fast": [10, 20, 30], "slow": [50, 100], "trend": [150, 200]},
    "donchian": {"entry": [20, 55, 100], "exit": [10, 20]},
    "supertrend_adx": {"st_mult": [2.0, 3.0, 4.0], "adx_threshold": [20.0, 25.0]},
}


# --------------------------------------------------------------------------
# Tamaño de posición por volatilidad (tipo Turtle)
# --------------------------------------------------------------------------

def atr_position_sizing(positions, high, low, close, risk=0.01, atr_window=20,
                        stop_mult=2.0, max_leverage=1.0):
    """Convierte señales -1/0/1 en fracciones del capital.

    Al abrir cada operación se fija un tamaño tal que un movimiento en
    contra de `stop_mult` * ATR cueste `risk` del capital:
        tamaño = risk / (stop_mult * ATR / precio), limitado a max_leverage.
    El tamaño se mantiene hasta cerrar la operación (sin rebalanceos). Si
    aún no hay ATR al abrir, esa operación se queda con tamaño 0.
    """
    if risk <= 0 or stop_mult <= 0 or max_leverage <= 0:
        raise ValueError("risk, stop_mult and max_leverage must be positive")
    atr_values = atr(high, low, close, atr_window)
    sized = [0.0] * len(positions)
    size, prev = 0.0, 0
    for i, signal in enumerate(positions):
        if signal != prev and signal != 0:
            if atr_values[i]:
                size = min(risk * close[i] / (stop_mult * atr_values[i]), max_leverage)
            else:
                size = 0.0
        sized[i] = signal * size
        prev = signal
    return sized


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

def _sign(x):
    return (x > 0) - (x < 0)


def backtest(close, positions, cost=0.001, periods_per_year=252):
    """Backtest de una exposición por barra sobre precios de cierre.

    `positions[i]` es la fracción del capital expuesta (negativa = corto)
    desde el cierre de i hasta el de i+1; admite tamaños fraccionarios.
    `cost` es comisión + slippage por lado sobre el nocional operado.
    La exposición se mantiene constante respecto al capital en cada barra.
    """
    if len(close) != len(positions):
        raise ValueError("close and positions must have the same length")
    equity = [1.0]
    returns, trades = [], []
    entry_equity, prev = None, 0
    for i in range(len(close) - 1):
        pos = positions[i]
        value = equity[-1]
        if _sign(pos) != _sign(prev):
            # Cierra la operación anterior (si la hay) y abre la nueva.
            value *= 1 - cost * abs(prev)
            if prev:
                trades.append(value / entry_equity - 1)
            value *= 1 - cost * abs(pos)
            if pos:
                entry_equity = value
        elif pos != prev:
            value *= 1 - cost * abs(pos - prev)
        value *= 1 + pos * (close[i + 1] / close[i] - 1)
        returns.append(value / equity[-1] - 1)
        equity.append(value)
        prev = pos
    if prev:
        equity[-1] *= 1 - cost * abs(prev)
        trades.append(equity[-1] / entry_equity - 1)

    peak, max_dd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, 1 - v / peak)

    years = (len(equity) - 1) / periods_per_year
    total_return = equity[-1] - 1
    cagr = equity[-1] ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else 0.0
    sharpe = 0.0
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
        sharpe = mean / std * math.sqrt(periods_per_year) if std > 0 else 0.0
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    exposed = positions[:-1]
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "exposure": sum(abs(p) for p in exposed) / max(len(exposed), 1),
        "equity": equity,
    }


# --------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------

def _param_combinations(grid):
    keys = list(grid)
    for values in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, values))
        if params.get("fast", 0) >= params.get("slow", math.inf):
            continue
        yield params


def walk_forward(high, low, close, strategy, param_grid=None, train=756, test=252,
                 objective="sharpe", cost=0.001, periods_per_year=252,
                 allow_short=False, sizing=None):
    """Optimiza en una ventana de entrenamiento y evalúa en la siguiente.

    Por cada bloque: prueba todas las combinaciones de `param_grid` sobre
    las `train` barras previas, elige la de mejor `objective` (una clave
    de backtest(), p. ej. "sharpe" o "cagr") y la aplica a las `test`
    barras siguientes. Las señales se calculan desde el inicio de la
    ventana de entrenamiento, así que el bloque de test arranca con los
    indicadores ya calientes, pero nunca con datos futuros.

    `sizing` es un dict opcional con argumentos para atr_position_sizing().
    Devuelve las estadísticas fuera de muestra (desde la barra `train`),
    las posiciones concatenadas y los parámetros elegidos en cada bloque.
    """
    if train <= 0 or test <= 0:
        raise ValueError("train and test must be positive")
    if len(close) < train + test:
        raise ValueError("not enough data for one train + test fold")
    func = STRATEGIES[strategy] if isinstance(strategy, str) else strategy
    if param_grid is None:
        param_grid = PARAM_GRIDS[strategy]

    positions = [0.0] * len(close)
    folds = []
    for start in range(train, len(close), test):
        lo, hi = start - train, min(start + test, len(close))
        h, l, c = high[lo:hi], low[lo:hi], close[lo:hi]
        best = None
        for params in _param_combinations(param_grid):
            pos = func(h, l, c, allow_short=allow_short, **params)
            if sizing:
                pos = atr_position_sizing(pos, h, l, c, **sizing)
            score = backtest(c[:train], pos[:train], cost, periods_per_year)[objective]
            if best is None or score > best[0]:
                best = (score, params, pos)
        score, params, pos = best
        positions[start:hi] = pos[train:]
        folds.append({"start": start, "end": hi, "params": params, "train_score": score})

    stats = backtest(close[train:], positions[train:], cost, periods_per_year)
    return {"stats": stats, "positions": positions, "folds": folds}


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
            f"CAGR {stats['cagr']:>6.1%}  sharpe {stats['sharpe']:>5.2f}  "
            f"maxDD {stats['max_drawdown']:>6.1%}  trades {stats['trades']:>4}  "
            f"win {stats['win_rate']:>5.1%}  expo {stats['exposure']:>5.1%}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="?", help="CSV con columnas high, low, close")
    parser.add_argument("--demo", action="store_true", help="usar datos sintéticos")
    parser.add_argument("--strategy", choices=["all", *STRATEGIES], default="all")
    parser.add_argument("--cost", type=float, default=0.001,
                        help="coste por lado (comisión + slippage), por defecto 0.001")
    parser.add_argument("--periods-per-year", type=int, default=252)
    parser.add_argument("--short", action="store_true", help="permitir cortos")
    sizing = parser.add_argument_group("tamaño por ATR (se activa con --risk)")
    sizing.add_argument("--risk", type=float,
                        help="fracción del capital arriesgada por operación, p. ej. 0.01")
    sizing.add_argument("--stop-mult", type=float, default=2.0,
                        help="stop de referencia en múltiplos de ATR (defecto 2)")
    sizing.add_argument("--max-leverage", type=float, default=1.0,
                        help="exposición máxima por operación (defecto 1)")
    wf = parser.add_argument_group("walk-forward")
    wf.add_argument("--walk-forward", action="store_true",
                    help="optimizar por bloques y evaluar fuera de muestra")
    wf.add_argument("--train", type=int, default=756, help="barras de entrenamiento")
    wf.add_argument("--test", type=int, default=252, help="barras de test por bloque")
    wf.add_argument("--objective", default="sharpe",
                    choices=["sharpe", "cagr", "total_return"])
    args = parser.parse_args(argv)

    if args.demo:
        high, low, close = synthetic_data()
    elif args.csv:
        high, low, close = load_csv(args.csv)
    else:
        parser.error("indica un CSV o usa --demo")

    sizing_args = None
    if args.risk is not None:
        sizing_args = {"risk": args.risk, "stop_mult": args.stop_mult,
                       "max_leverage": args.max_leverage}
    names = list(STRATEGIES) if args.strategy == "all" else [args.strategy]

    if args.walk_forward:
        oos = slice(args.train, None)
        bh = backtest(close[oos], [1] * len(close[oos]), args.cost, args.periods_per_year)
        print(f"Fuera de muestra: barras {args.train}-{len(close) - 1}")
        print(format_report("buy_and_hold", bh))
        for name in names:
            result = walk_forward(high, low, close, name, train=args.train,
                                  test=args.test, objective=args.objective,
                                  cost=args.cost, periods_per_year=args.periods_per_year,
                                  allow_short=args.short, sizing=sizing_args)
            print(format_report(name, result["stats"]))
            for fold in result["folds"]:
                params = ", ".join(f"{k}={v}" for k, v in fold["params"].items())
                print(f"    [{fold['start']}-{fold['end']}) {params}  "
                      f"({args.objective} train {fold['train_score']:.2f})")
        return

    bh = backtest(close, [1] * len(close), args.cost, args.periods_per_year)
    print(format_report("buy_and_hold", bh))
    for name in names:
        positions = STRATEGIES[name](high, low, close, allow_short=args.short)
        if sizing_args:
            positions = atr_position_sizing(positions, high, low, close, **sizing_args)
        print(format_report(name, backtest(close, positions, args.cost,
                                           args.periods_per_year)))


if __name__ == "__main__":
    main()
