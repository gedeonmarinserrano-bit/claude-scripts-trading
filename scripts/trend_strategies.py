"""Estrategias tendenciales con backtest, sizing, walk-forward y carteras.

Estrategias (solo largos por defecto; --short activa los cortos):
    - ma_crossover:       cruce EMA rápida/lenta + filtro SMA 200 + stop ATR.
    - donchian_breakout:  ruptura de canal Donchian (tipo Turtle).
    - supertrend_adx:     Supertrend filtrado por ADX + Chandelier Exit.
    - trend_ensemble:     media de 4 cruces de EMAs (8/32 ... 64/256); pensada
                          para usarse con objetivo de volatilidad (--vol-target).

Cada estrategia devuelve una lista de posiciones (1 = largo, -1 = corto,
0 = fuera; trend_ensemble da valores intermedios), calculada con datos
hasta el cierre de cada barra. El backtest
aplica la posición de la barra i al retorno de i a i+1, así que no hay
lookahead.

Uso:
    python -m scripts.trend_strategies datos.csv --strategy donchian
    python -m scripts.trend_strategies --demo --short --risk 0.01
    python -m scripts.trend_strategies --demo --walk-forward
    python -m scripts.trend_strategies spx.csv --strategy trend_ensemble --vol-target 0.15
    python -m scripts.trend_strategies spx.csv ndx.csv oro.csv --cash-rate 0.02
    python -m scripts.trend_strategies spx.csv bonos.csv oro.csv \\
        --strategy trend_ensemble --vol-target 0.15 --portfolio-vol 0.10

El CSV debe tener columna close y, idealmente, date, high y low (open es
opcional). Con varios CSV se evalúa una cartera en sus fechas comunes.
Solo usa la librería estándar.
"""

import argparse
import csv
import datetime
import itertools
import math
import os
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


def trend_ensemble(high, low, close, pairs=((8, 32), (16, 64), (32, 128), (64, 256)),
                   allow_short=False):
    """Conjunto de cruces de EMAs: la posición es la media de sus votos.

    Cada par (rápida, lenta) vota 1 si la EMA rápida está por encima de la
    lenta y 0 si no (-1 con allow_short). La posición resultante va de 0 a
    1 (o de -1 a 1) y cambia de forma gradual: no depende de acertar con un
    único par de medias. Sin stops: el riesgo lo controla el sizing
    (pensada para usarse con volatility_target()).
    """
    if not pairs:
        raise ValueError("pairs must not be empty")
    averages = [(ema(close, fast), ema(close, slow)) for fast, slow in pairs]
    positions = [0.0] * len(close)
    for i in range(len(close)):
        votes = []
        for fast, slow in averages:
            if fast[i] is None or slow[i] is None:
                break
            if fast[i] > slow[i]:
                votes.append(1)
            else:
                votes.append(-1 if allow_short and fast[i] < slow[i] else 0)
        else:
            positions[i] = sum(votes) / len(votes)
    return positions


STRATEGIES = {
    "ma_crossover": ma_crossover,
    "donchian": donchian_breakout,
    "supertrend_adx": supertrend_adx,
    "trend_ensemble": trend_ensemble,
}

# Rejillas de parámetros que prueba el walk-forward.
PARAM_GRIDS = {
    "ma_crossover": {"fast": [10, 20, 30], "slow": [50, 100], "trend": [150, 200]},
    "donchian": {"entry": [20, 55, 100], "exit": [10, 20]},
    "supertrend_adx": {"st_mult": [2.0, 3.0, 4.0], "adx_threshold": [20.0, 25.0]},
    # El conjunto ya promedia varios horizontes: no se optimiza.
    "trend_ensemble": {},
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


def volatility_target(positions, close, target_vol=0.15, span=32, max_leverage=1.0,
                      buffer=0.1, periods_per_year=252):
    """Escala las señales para que la volatilidad anual ronde `target_vol`.

    La volatilidad se estima con una media exponencial (`span` barras) de
    los retornos logarítmicos al cuadrado, usando datos hasta la barra
    actual. Exposición = señal * target_vol / volatilidad, con un máximo
    de `max_leverage` en valor absoluto. Para no operar a diario, la
    exposición solo se cambia si se aleja `buffer` o más de la actual (o
    si la señal pasa a 0). Hasta tener `span` retornos la exposición es 0.
    """
    if target_vol <= 0 or span <= 0 or max_leverage <= 0 or buffer < 0:
        raise ValueError("target_vol, span and max_leverage must be positive")
    alpha = 2 / (span + 1)
    sized = [0.0] * len(positions)
    variance, current = None, 0.0
    squared = []
    for i in range(1, len(positions)):
        r2 = math.log(close[i] / close[i - 1]) ** 2
        if variance is None:
            squared.append(r2)
            if len(squared) == span:
                variance = sum(squared) / span
        else:
            variance = alpha * r2 + (1 - alpha) * variance
        if variance is None:
            continue
        vol = math.sqrt(variance * periods_per_year)
        scale = target_vol / vol if vol > 0 else max_leverage
        desired = max(-max_leverage, min(max_leverage, positions[i] * scale))
        if desired == 0 or abs(desired - current) >= buffer:
            current = desired
        sized[i] = current
    return sized


def apply_sizing(positions, high, low, close, sizing=None):
    """Aplica el sizing indicado en el dict `sizing`.

    Con la clave `target_vol` usa volatility_target(); si no, los
    argumentos van a atr_position_sizing(). None deja las señales igual.
    """
    if not sizing:
        return positions
    if "target_vol" in sizing:
        return volatility_target(positions, close, **sizing)
    return atr_position_sizing(positions, high, low, close, **sizing)


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

def _sign(x):
    return (x > 0) - (x < 0)


def _bar_rate(annual_rate, periods_per_year):
    return (1 + annual_rate) ** (1 / periods_per_year) - 1


def _cash_return(positions, rf):
    """Interés del efectivo no usado en largos.

    Los largos consumen efectivo; los cortos no (el colateral y lo obtenido
    con la venta siguen cobrando interés). Si los largos superan el 100 %
    del capital, el exceso paga el mismo tipo como financiación.
    """
    return (1 - sum(max(p, 0) for p in positions)) * rf


def _summary(equity, returns, rf, periods_per_year):
    peak, max_dd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, 1 - v / peak)
    years = (len(equity) - 1) / periods_per_year
    cagr = equity[-1] ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else 0.0
    sharpe = 0.0
    if len(returns) > 1:
        excess = [r - rf for r in returns]
        mean = sum(excess) / len(excess)
        std = math.sqrt(sum((r - mean) ** 2 for r in excess) / (len(excess) - 1))
        sharpe = mean / std * math.sqrt(periods_per_year) if std > 1e-12 else 0.0
    return {"total_return": equity[-1] - 1, "cagr": cagr, "sharpe": sharpe,
            "max_drawdown": max_dd, "equity": equity}


def backtest(close, positions, cost=0.001, periods_per_year=252, cash_rate=0.0):
    """Backtest de una exposición por barra sobre precios de cierre.

    `positions[i]` es la fracción del capital expuesta (negativa = corto)
    desde el cierre de i hasta el de i+1; admite tamaños fraccionarios.
    `cost` es comisión + slippage por lado sobre el nocional operado.
    `cash_rate` es el tipo anual que cobra el efectivo no invertido; el
    Sharpe se calcula sobre la rentabilidad en exceso de ese tipo.
    La exposición se mantiene constante respecto al capital en cada barra.
    """
    if len(close) != len(positions):
        raise ValueError("close and positions must have the same length")
    rf = _bar_rate(cash_rate, periods_per_year)
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
        value *= 1 + pos * (close[i + 1] / close[i] - 1) + _cash_return([pos], rf)
        returns.append(value / equity[-1] - 1)
        equity.append(value)
        prev = pos
    if prev:
        equity[-1] *= 1 - cost * abs(prev)
        trades.append(equity[-1] / entry_equity - 1)

    stats = _summary(equity, returns, rf, periods_per_year)
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    exposed = positions[:-1]
    stats.update({
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "exposure": sum(abs(p) for p in exposed) / max(len(exposed), 1),
    })
    return stats


def backtest_portfolio(closes, positions, cost=0.001, periods_per_year=252,
                       cash_rate=0.0):
    """Backtest de varios activos alineados en las mismas fechas.

    `closes` y `positions` son listas (una por activo) de igual longitud;
    cada posición es la fracción del capital total en ese activo. Los
    pesos se mantienen constantes respecto al capital en cada barra.
    Devuelve las mismas métricas que backtest() salvo las de operaciones
    ganadoras/perdedoras; `trades` cuenta las aperturas.
    """
    if len(closes) != len(positions) or not closes:
        raise ValueError("need one positions list per asset")
    n = len(closes[0])
    if any(len(c) != n for c in closes) or any(len(p) != n for p in positions):
        raise ValueError("all series must have the same length")
    rf = _bar_rate(cash_rate, periods_per_year)
    equity, returns = [1.0], []
    prev = [0] * len(closes)
    trades, gross = 0, 0.0
    for i in range(n - 1):
        pos = [p[i] for p in positions]
        turnover = sum(abs(a - b) for a, b in zip(pos, prev))
        trades += sum(1 for a, b in zip(pos, prev) if a and _sign(a) != _sign(b))
        value = equity[-1] * (1 - cost * turnover)
        market = sum(p * (c[i + 1] / c[i] - 1) for p, c in zip(pos, closes))
        value *= 1 + market + _cash_return(pos, rf)
        returns.append(value / equity[-1] - 1)
        equity.append(value)
        gross += sum(abs(p) for p in pos)
        prev = pos
    equity[-1] *= 1 - cost * sum(abs(p) for p in prev)
    stats = _summary(equity, returns, rf, periods_per_year)
    stats.update({"trades": trades, "exposure": gross / max(n - 1, 1)})
    return stats


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
                 allow_short=False, sizing=None, cash_rate=0.0):
    """Optimiza en una ventana de entrenamiento y evalúa en la siguiente.

    Por cada bloque: prueba todas las combinaciones de `param_grid` sobre
    las `train` barras previas, elige la de mejor `objective` (una clave
    de backtest(), p. ej. "sharpe" o "cagr") y la aplica a las `test`
    barras siguientes. Las señales se calculan desde el inicio de la
    ventana de entrenamiento, así que el bloque de test arranca con los
    indicadores ya calientes, pero nunca con datos futuros.

    `sizing` es un dict opcional para apply_sizing().
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
            pos = apply_sizing(pos, h, l, c, sizing)
            score = backtest(c[:train], pos[:train], cost, periods_per_year,
                             cash_rate)[objective]
            if best is None or score > best[0]:
                best = (score, params, pos)
        score, params, pos = best
        positions[start:hi] = pos[train:]
        folds.append({"start": start, "end": hi, "params": params, "train_score": score})

    stats = backtest(close[train:], positions[train:], cost, periods_per_year, cash_rate)
    return {"stats": stats, "positions": positions, "folds": folds}


# --------------------------------------------------------------------------
# Cartera
# --------------------------------------------------------------------------

def portfolio_vol_target(closes, positions, target_vol=0.10, span=32, max_gross=1.0,
                         buffer=0.05, periods_per_year=252):
    """Escala todas las posiciones de una cartera por un mismo factor.

    La volatilidad de la cartera se estima con los pesos de cada barra y
    una matriz de covarianzas exponencial (`span` barras) de los retornos
    de los activos, con datos hasta esa barra. Factor = target_vol /
    volatilidad, limitado para que la exposición bruta no supere
    `max_gross`. Así la cartera sube la exposición cuando la
    diversificación reduce el riesgo y la baja cuando los activos se
    mueven juntos. Cada peso solo se cambia si se aleja `buffer` o más
    del actual (o si pasa a 0), salvo que eso deje la exposición bruta por
    encima de `max_gross`. Hasta tener `span` retornos, los pesos son 0.
    """
    if target_vol <= 0 or span <= 0 or max_gross <= 0 or buffer < 0:
        raise ValueError("target_vol, span and max_gross must be positive")
    k, n = len(closes), len(closes[0])
    alpha = 2 / (span + 1)
    cov, seed = None, []
    current = [0.0] * k
    out = [[0.0] * n for _ in range(k)]
    for i in range(1, n):
        r = [closes[a][i] / closes[a][i - 1] - 1 for a in range(k)]
        if cov is None:
            seed.append(r)
            if len(seed) == span:
                cov = [[sum(x[a] * x[b] for x in seed) / span for b in range(k)]
                       for a in range(k)]
            if cov is None:
                continue
        else:
            cov = [[alpha * r[a] * r[b] + (1 - alpha) * cov[a][b] for b in range(k)]
                   for a in range(k)]
        w = [positions[a][i] for a in range(k)]
        gross = sum(abs(x) for x in w)
        variance = sum(w[a] * w[b] * cov[a][b] for a in range(k) for b in range(k))
        if gross == 0:
            factor = 0.0
        else:
            vol = math.sqrt(max(variance, 0.0) * periods_per_year)
            factor = target_vol / vol if vol > 0 else math.inf
            factor = min(factor, max_gross / gross)
        desired = [x * factor for x in w]
        for a in range(k):
            if desired[a] == 0 or abs(desired[a] - current[a]) >= buffer:
                current[a] = desired[a]
        # Con el buffer, los pesos que no se tocan pueden dejar la cartera
        # por encima del límite: entonces se rebalancea todo.
        if sum(abs(x) for x in current) > max_gross + 1e-12:
            current = desired
        for a in range(k):
            out[a][i] = current[a]
    return out


def align_assets(assets):
    """Recorta varios activos a las fechas que tienen todos en común.

    `assets` es {nombre: (fechas, high, low, close)}. Devuelve
    (fechas, {nombre: (high, low, close)}).
    """
    if not assets:
        raise ValueError("no assets")
    common = set.intersection(*(set(a[0]) for a in assets.values()))
    dates = sorted(common)
    if not dates:
        raise ValueError("assets have no dates in common")
    aligned = {}
    for name, (asset_dates, high, low, close) in assets.items():
        index = {d: i for i, d in enumerate(asset_dates)}
        rows = [index[d] for d in dates]
        aligned[name] = ([high[i] for i in rows], [low[i] for i in rows],
                         [close[i] for i in rows])
    return dates, aligned


def run_portfolio(assets, strategy, allow_short=False, sizing=None, cost=0.001,
                  periods_per_year=252, cash_rate=0.0, walk_forward_args=None,
                  portfolio_vol=None):
    """Aplica una estrategia a cada activo y los combina en una cartera.

    `assets` es {nombre: (high, low, close)} ya alineado (ver align_assets).
    Sin sizing o con objetivo de volatilidad, cada activo recibe 1/N del
    capital. Con sizing por ATR, cada operación arriesga `risk` del capital
    total, como en el sistema Turtle, así que la exposición bruta puede
    superar el 100 % (el exceso se financia al tipo del efectivo).

    Con `walk_forward_args` (dict con train, test, objective) los
    parámetros se eligen por activo y bloque, y las métricas empiezan en
    la barra `train`. Con `portfolio_vol` (dict de argumentos para
    portfolio_vol_target) se escala además la cartera completa.
    Devuelve las métricas de la cartera y, por activo, las posiciones y
    las métricas del activo por separado.
    """
    names = list(assets)
    atr_sizing = bool(sizing) and "target_vol" not in sizing
    weight = 1.0 if atr_sizing else 1.0 / len(names)
    start = walk_forward_args["train"] if walk_forward_args else 0
    per_asset = {}
    for name in names:
        high, low, close = assets[name]
        if walk_forward_args:
            result = walk_forward(high, low, close, strategy, cost=cost,
                                  periods_per_year=periods_per_year,
                                  allow_short=allow_short, sizing=sizing,
                                  cash_rate=cash_rate, **walk_forward_args)
            positions = result["positions"]
        else:
            positions = STRATEGIES[strategy](high, low, close, allow_short=allow_short)
            positions = apply_sizing(positions, high, low, close, sizing)
        standalone = backtest(close[start:], positions[start:], cost,
                              periods_per_year, cash_rate)
        per_asset[name] = {"positions": [p * weight for p in positions],
                           "stats": standalone}
    if portfolio_vol:
        scaled = portfolio_vol_target([assets[n][2] for n in names],
                                      [per_asset[n]["positions"] for n in names],
                                      **portfolio_vol)
        for name, positions in zip(names, scaled):
            per_asset[name]["positions"] = positions
    stats = backtest_portfolio(
        [assets[n][2][start:] for n in names],
        [per_asset[n]["positions"][start:] for n in names],
        cost, periods_per_year, cash_rate)
    return {"stats": stats, "assets": per_asset}


# --------------------------------------------------------------------------
# Datos y CLI
# --------------------------------------------------------------------------

_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y%m%d"]


def _parse_dates(values):
    """Detecta el formato que sirve para todas las fechas del archivo."""
    for fmt in _DATE_FORMATS:
        try:
            return [datetime.datetime.strptime(v.strip(), fmt).date() for v in values]
        except ValueError:
            continue
    raise ValueError(f"unrecognised date format, e.g. {values[0]!r}")


def _read_csv(path):
    """Lee las columnas de precios; devuelve (fechas en texto o None, high, low, close)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = {name.strip().lower(): name for name in reader.fieldnames or []}
        close_col = fields.get("close") or fields.get("adj close")
        if close_col is None:
            raise ValueError("missing columns: close")
        high_col = fields.get("high", close_col)
        low_col = fields.get("low", close_col)
        date_col = fields.get("date")
        raw_dates, high, low, close = [], [], [], []
        for row in reader:
            try:
                values = (float(row[high_col]), float(row[low_col]), float(row[close_col]))
            except (TypeError, ValueError):
                continue
            if values[2] <= 0:
                continue
            high.append(values[0])
            low.append(values[1])
            close.append(values[2])
            raw_dates.append(row[date_col] if date_col else None)
    if not close:
        raise ValueError(f"{path}: no valid rows")
    return (raw_dates if date_col else None), high, low, close


def load_csv(path):
    """Lee un CSV de precios y devuelve (high, low, close) en el orden del archivo.

    Necesita una columna `close` (o `adj close` si no hay `close`); si
    faltan `high`/`low` se usa el cierre (el ATR será entonces el rango
    entre cierres). Las filas con valores no numéricos (p. ej. "null" o
    ".") se descartan.
    """
    return _read_csv(path)[1:]


def load_csv_dated(path):
    """Como load_csv, pero exige columna `date` y devuelve
    (fechas, high, low, close) ordenado por fecha."""
    raw_dates, high, low, close = _read_csv(path)
    if raw_dates is None:
        raise ValueError(f"{path}: missing columns: date")
    dates = _parse_dates(raw_dates)
    order = sorted(range(len(dates)), key=dates.__getitem__)
    dates = [dates[i] for i in order]
    if any(a == b for a, b in zip(dates, dates[1:])):
        raise ValueError(f"{path}: duplicated dates")
    return (dates, [high[i] for i in order], [low[i] for i in order],
            [close[i] for i in order])


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
    line = (f"{name:<16} ret {stats['total_return']:>8.1%}  "
            f"CAGR {stats['cagr']:>6.1%}  sharpe {stats['sharpe']:>5.2f}  "
            f"maxDD {stats['max_drawdown']:>6.1%}  trades {stats['trades']:>4}  ")
    if "win_rate" in stats:
        line += f"win {stats['win_rate']:>5.1%}  "
    return line + f"expo {stats['exposure']:>5.1%}"


def _run_portfolio_cli(args, paths, sizing_args, names):
    portfolio_vol = None
    if args.portfolio_vol is not None:
        portfolio_vol = {"target_vol": args.portfolio_vol, "span": args.vol_span,
                         "max_gross": args.max_gross,
                         "buffer": args.rebalance_buffer / len(paths),
                         "periods_per_year": args.periods_per_year}
    assets = {}
    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        if name in assets:
            raise SystemExit(f"duplicated asset name: {name}")
        assets[name] = load_csv_dated(path)
    dates, aligned = align_assets(assets)
    wf_args = None
    start = 0
    if args.walk_forward:
        wf_args = {"train": args.train, "test": args.test, "objective": args.objective}
        start = args.train
    if len(dates) <= start + 1:
        raise SystemExit("not enough common dates")
    print(f"Cartera de {len(aligned)} activos: {', '.join(aligned)}")
    print(f"Fechas comunes: {dates[0]} a {dates[-1]} ({len(dates)} barras); "
          f"métricas desde {dates[start]}"
          + (" (fuera de muestra)" if wf_args else ""))
    bh = backtest_portfolio(
        [a[2][start:] for a in aligned.values()],
        [[1 / len(aligned)] * (len(dates) - start) for _ in aligned],
        args.cost, args.periods_per_year, args.cash_rate)
    print(format_report("buy_and_hold", bh))
    for name in names:
        result = run_portfolio(aligned, name, allow_short=args.short,
                               sizing=sizing_args, cost=args.cost,
                               periods_per_year=args.periods_per_year,
                               cash_rate=args.cash_rate, walk_forward_args=wf_args,
                               portfolio_vol=portfolio_vol)
        print(format_report(name, result["stats"]))
        for asset, data in result["assets"].items():
            print("    " + format_report(asset, data["stats"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="*",
                        help="CSV con columnas date, high, low, close; con varios "
                             "archivos se evalúa una cartera")
    parser.add_argument("--demo", action="store_true", help="usar datos sintéticos")
    parser.add_argument("--strategy", choices=["all", *STRATEGIES], default="all")
    parser.add_argument("--cost", type=float, default=0.001,
                        help="coste por lado (comisión + slippage), por defecto 0.001")
    parser.add_argument("--cash-rate", type=float, default=0.0,
                        help="interés anual del efectivo no invertido, p. ej. 0.02")
    parser.add_argument("--periods-per-year", type=int, default=252)
    parser.add_argument("--short", action="store_true", help="permitir cortos")
    sizing = parser.add_argument_group(
        "tamaño de posición (--risk para ATR o --vol-target para volatilidad)")
    sizing.add_argument("--risk", type=float,
                        help="fracción del capital arriesgada por operación, p. ej. 0.01")
    sizing.add_argument("--stop-mult", type=float, default=2.0,
                        help="stop de referencia en múltiplos de ATR (defecto 2)")
    sizing.add_argument("--vol-target", type=float,
                        help="volatilidad anual objetivo por activo, p. ej. 0.15")
    sizing.add_argument("--vol-span", type=int, default=32,
                        help="barras de la media exponencial de volatilidad (defecto 32)")
    sizing.add_argument("--rebalance-buffer", type=float, default=0.1,
                        help="cambio mínimo de exposición para rebalancear (defecto 0.1)")
    sizing.add_argument("--max-leverage", type=float, default=1.0,
                        help="exposición máxima por activo (defecto 1)")
    sizing.add_argument("--portfolio-vol", type=float,
                        help="solo carteras: volatilidad anual objetivo de la cartera "
                             "completa, p. ej. 0.10")
    sizing.add_argument("--max-gross", type=float, default=1.0,
                        help="solo carteras: exposición bruta máxima con "
                             "--portfolio-vol (defecto 1)")
    wf = parser.add_argument_group("walk-forward")
    wf.add_argument("--walk-forward", action="store_true",
                    help="optimizar por bloques y evaluar fuera de muestra")
    wf.add_argument("--train", type=int, default=756, help="barras de entrenamiento")
    wf.add_argument("--test", type=int, default=252, help="barras de test por bloque")
    wf.add_argument("--objective", default="sharpe",
                    choices=["sharpe", "cagr", "total_return"])
    args = parser.parse_args(argv)

    if args.demo and args.csv:
        parser.error("usa --demo o archivos CSV, no ambos")
    if not args.demo and not args.csv:
        parser.error("indica uno o más CSV o usa --demo")

    if args.risk is not None and args.vol_target is not None:
        parser.error("usa --risk o --vol-target, no ambos")
    sizing_args = None
    if args.risk is not None:
        sizing_args = {"risk": args.risk, "stop_mult": args.stop_mult,
                       "max_leverage": args.max_leverage}
    elif args.vol_target is not None:
        sizing_args = {"target_vol": args.vol_target, "span": args.vol_span,
                       "buffer": args.rebalance_buffer,
                       "max_leverage": args.max_leverage,
                       "periods_per_year": args.periods_per_year}
    names = list(STRATEGIES) if args.strategy == "all" else [args.strategy]

    if len(args.csv) > 1:
        _run_portfolio_cli(args, args.csv, sizing_args, names)
        return
    if args.portfolio_vol is not None:
        parser.error("--portfolio-vol necesita dos o más CSV")

    if args.demo:
        high, low, close = synthetic_data()
    else:
        high, low, close = load_csv(args.csv[0])

    if args.walk_forward:
        oos = slice(args.train, None)
        bh = backtest(close[oos], [1] * len(close[oos]), args.cost,
                      args.periods_per_year, args.cash_rate)
        print(f"Fuera de muestra: barras {args.train}-{len(close) - 1}")
        print(format_report("buy_and_hold", bh))
        for name in names:
            result = walk_forward(high, low, close, name, train=args.train,
                                  test=args.test, objective=args.objective,
                                  cost=args.cost, periods_per_year=args.periods_per_year,
                                  allow_short=args.short, sizing=sizing_args,
                                  cash_rate=args.cash_rate)
            print(format_report(name, result["stats"]))
            for fold in result["folds"]:
                params = ", ".join(f"{k}={v}" for k, v in fold["params"].items())
                print(f"    [{fold['start']}-{fold['end']}) {params}  "
                      f"({args.objective} train {fold['train_score']:.2f})")
        return

    bh = backtest(close, [1] * len(close), args.cost, args.periods_per_year,
                  args.cash_rate)
    print(format_report("buy_and_hold", bh))
    for name in names:
        positions = STRATEGIES[name](high, low, close, allow_short=args.short)
        positions = apply_sizing(positions, high, low, close, sizing_args)
        print(format_report(name, backtest(close, positions, args.cost,
                                           args.periods_per_year, args.cash_rate)))


if __name__ == "__main__":
    main()
