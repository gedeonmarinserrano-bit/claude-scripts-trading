"""Pruebas de robustez de la estrategia RNC+FVG.

    python backtest/evaluar.py datos_1m.csv [--oos 0.3]
    python backtest/evaluar.py datos_5m.csv --bar-sec 300   # todo en 5 minutos

1. Backtest con los parámetros por defecto (los mismos del script Pine).
2. Separación dentro de muestra (IS, primeras fechas) / fuera de muestra (OOS, últimas).
3. Rejilla de parámetros: se elige la mejor combinación en IS y se mira cómo le va en OOS,
   y qué parte de la rejilla sigue siendo rentable en OOS (si solo funciona una
   combinación concreta, es sobreajuste).
4. Monte Carlo: se barajan las operaciones para ver el drawdown que cabe esperar.
"""
from __future__ import annotations

import argparse
import itertools
import random
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import rnc_fvg as R  # noqa: E402

GRID = {
    "brk_body": [0.5, 0.8, 1.1],
    "use_acc": [True, False],
    "ifvg_body": [0.3, 0.5, 0.8],
    "rr": [2.0, 3.0],
}


def monte_carlo_dd(pnls: list[float], n: int = 2000, seed: int = 1) -> tuple[float, float]:
    rnd = random.Random(seed)
    dds = []
    for _ in range(n):
        s = pnls[:]
        rnd.shuffle(s)
        eq = peak = dd = 0.0
        for x in s:
            eq += x
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        dds.append(dd)
    dds.sort()
    return dds[len(dds) // 2], dds[int(len(dds) * 0.95)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--bar-sec", type=int, default=60, help="duración de las velas del CSV en segundos (300 = todo en M5)")
    ap.add_argument("--oos", type=float, default=0.3, help="fracción final de días para fuera de muestra")
    a = ap.parse_args()

    df = R.load_csv(a.csv)
    days = sorted(set(df.index.date))
    cut = days[int(len(days) * (1 - a.oos))]
    is_df = df[df.index.date < cut]
    oos_df = df[df.index.date >= cut]
    print(f"Datos: {df.index[0]} → {df.index[-1]} ({len(days)} días). Corte IS/OOS: {cut}\n")

    base = R.Params(bar_sec=a.bar_sec)
    for name, part in (("TODO", df), ("IS", is_df), ("OOS", oos_df)):
        print(f"Parámetros por defecto · {name}: {R.stats(R.run(part, base))}")

    rows = []
    keys = list(GRID)
    for combo in itertools.product(*GRID.values()):
        p = replace(base, **dict(zip(keys, combo)))
        s_is, s_oos = R.stats(R.run(is_df, p)), R.stats(R.run(oos_df, p))
        rows.append({**dict(zip(keys, combo)),
                     **{f"is_{k}": v for k, v in s_is.items()},
                     **{f"oos_{k}": v for k, v in s_oos.items()}})
    g = pd.DataFrame(rows)
    g.to_csv("rejilla.csv", index=False)
    ok = g[g["is_trades"] >= 20]
    print(f"\nRejilla: {len(g)} combinaciones (guardada en rejilla.csv)")
    if len(ok):
        best = ok.sort_values("is_pf", ascending=False).iloc[0]
        print("Mejor en IS:", best[keys].to_dict())
        print(f"  IS  → PF {best['is_pf']}, neto {best['is_net_$']} $, {best['is_trades']} ops")
        print(f"  OOS → PF {best.get('oos_pf')}, neto {best.get('oos_net_$')} $, {best.get('oos_trades')} ops")
    prof = (g.get("oos_net_$", pd.Series(dtype=float)).fillna(0) > 0).mean() * 100
    print(f"Combinaciones rentables fuera de muestra: {prof:.0f} %")

    tr = R.run(df, base)
    if tr:
        med, p95 = monte_carlo_dd([t.pnl for t in tr])
        print(f"\nMonte Carlo (parámetros por defecto): drawdown mediano {med:.0f} $, peor 5 % {p95:.0f} $")
        pd.DataFrame([t.__dict__ for t in tr]).to_csv("operaciones.csv", index=False)


if __name__ == "__main__":
    main()
