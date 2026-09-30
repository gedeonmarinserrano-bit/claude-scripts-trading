"""Backtest en Python de la estrategia "Ruptura Nivel Clave + FVG (M5 → M1)".

Replica la lógica de tradingview/RupturaNivelClaveFVG.pine sobre velas de 1 minuto.

Datos de entrada: CSV con columnas time, open, high, low, close (time en UTC o con zona
horaria). Uso:

    python backtest/rnc_fvg.py datos.csv
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, replace
from datetime import time as dtime

import pandas as pd

NY = "America/New_York"


@dataclass
class Params:
    trade_start: dtime = dtime(9, 30)
    trade_end: dtime = dtime(11, 0)
    ovn_start: dtime = dtime(18, 0)
    ovn_end: dtime = dtime(9, 30)
    flat_time: dtime = dtime(15, 55)
    max_trades: int = 2
    use_ovn: bool = True
    use_prev: bool = True
    atr_len: int = 14
    brk_body: float = 0.8
    fvg_min_tk: int = 4
    use_acc: bool = True
    acc_bars: int = 6
    acc_max_atr: float = 3.0
    wait_ret: int = 12
    ifvg_body: float = 0.5
    wait_ent: int = 30
    rr: float = 3.0
    sl_buf_tk: int = 4
    allow_long: bool = True
    allow_short: bool = True
    tick: float = 0.25
    point_value: float = 2.0       # MNQ: 2 $ por punto
    commission: float = 0.62       # $ por contrato y lado
    slippage_tk: int = 1           # ticks por lado
    qty: int = 1


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: int
    entry: float
    sl: float
    tp: float
    level: str
    exit_time: pd.Timestamp | None = None
    exit: float | None = None
    reason: str = ""
    pnl: float = 0.0
    r: float = 0.0


def _in_range(t: dtime, a: dtime, b: dtime) -> bool:
    return a <= t < b if a < b else (t >= a or t < b)


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next(c for c in df.columns if c in ("time", "datetime", "date", "timestamp"))
    ts = pd.to_datetime(df[tcol], utc=True) if not str(df[tcol].iloc[0]).isdigit() \
        else pd.to_datetime(df[tcol].astype("int64"), unit="s" if len(str(df[tcol].iloc[0])) <= 10 else "ms", utc=True)
    out = df[["open", "high", "low", "close"]].astype(float)
    out.index = ts.dt.tz_convert(NY)
    return out.sort_index()[~out.index.duplicated()]


def daily_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Máx/Mín de la sesión anterior (día de futuros 18:00-17:00 NY)."""
    sess_day = (df.index + pd.Timedelta(hours=6)).date  # 18:00 NY pasa al día siguiente
    g = df.groupby(sess_day).agg(h=("high", "max"), l=("low", "min"))
    g[["prev_h", "prev_l"]] = g[["h", "l"]].shift(1)
    return pd.DataFrame({"day": sess_day}, index=df.index).join(g[["prev_h", "prev_l"]], on="day")


def run(df: pd.DataFrame, p: Params) -> list[Trade]:
    tk = p.tick
    lv = daily_levels(df)
    idx = df.index
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    prev_h, prev_l = lv["prev_h"].to_numpy(), lv["prev_l"].to_numpy()
    tod = [t.time() for t in idx]
    ns = idx.as_unit("ns").asi8  # nanosegundos

    # ATR M1 (Wilder)
    tr1 = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr1 = pd.Series(tr1).ewm(alpha=1 / p.atr_len, adjust=False).mean().to_numpy()

    TF5 = 300 * 10**9
    cO: list[float] = []; cH: list[float] = []; cL: list[float] = []; cC: list[float] = []
    bT = None; bO = bH = bL = bC = 0.0; bDone = True
    atr5 = None

    ovnH = ovnL = curOH = curOL = None
    used = {"OH": False, "OL": False, "PH": False, "PL": False}
    trades_today = 0
    st = 0; d = 0; zTop = zBot = ext = None; cnt5 = cnt1 = 0
    oTop: list[float] = []; oBot: list[float] = []
    pos: Trade | None = None
    trades: list[Trade] = []
    slip = p.slippage_tk * tk
    prev_in_trade = prev_in_ovn = False

    for i in range(len(c)):
        t = tod[i]
        in_trade = _in_range(t, p.trade_start, p.trade_end)
        in_ovn = _in_range(t, p.ovn_start, p.ovn_end)
        in_flat = _in_range(t, p.flat_time, dtime(16, 0))

        # --- gestión de la posición abierta (desde la vela siguiente a la entrada)
        if pos is not None and pos.entry_time != idx[i]:
            hit_sl = l[i] <= pos.sl if pos.direction == 1 else h[i] >= pos.sl
            hit_tp = h[i] >= pos.tp if pos.direction == 1 else l[i] <= pos.tp
            if hit_sl or hit_tp:
                # si en la misma vela se tocan ambos, se asume el stop (conservador)
                px, why = (pos.sl, "SL") if hit_sl else (pos.tp, "TP")
                if hit_sl:
                    px -= pos.direction * slip
                _close(pos, idx[i], px, why, p); trades.append(pos); pos = None
            elif in_flat:
                _close(pos, idx[i], c[i] - pos.direction * slip, "Hora", p); trades.append(pos); pos = None

        # --- niveles
        if in_ovn and not prev_in_ovn:
            curOH, curOL = h[i], l[i]
        elif in_ovn:
            curOH, curOL = max(curOH, h[i]), min(curOL, l[i])
        if not in_ovn and prev_in_ovn:
            ovnH, ovnL = curOH, curOL
        if in_trade and not prev_in_trade:
            used = dict.fromkeys(used, False); trades_today = 0

        # --- velas M5
        m5_closed = False
        blk = ns[i] // TF5 * TF5
        if bT is None or blk != bT:
            if not bDone:
                cO.append(bO); cH.append(bH); cL.append(bL); cC.append(bC); m5_closed = True
            bT, bO, bH, bL, bC, bDone = blk, o[i], h[i], l[i], c[i], False
        else:
            bH, bL, bC = max(bH, h[i]), min(bL, l[i]), c[i]
        if not bDone and ns[i] + 60 * 10**9 >= bT + TF5:
            cO.append(bO); cH.append(bH); cL.append(bL); cC.append(bC); bDone = True; m5_closed = True
        if m5_closed:
            n = len(cC)
            tr = cH[-1] - cL[-1] if n == 1 else max(cH[-1] - cL[-1], abs(cH[-1] - cC[-2]), abs(cL[-1] - cC[-2]))
            atr5 = tr if atr5 is None else atr5 + (tr - atr5) / p.atr_len

        cancel = just_set = False
        # --- 1) ruptura
        if st == 0 and m5_closed and in_trade and atr5 is not None and len(cC) >= p.acc_bars + 3:
            n = len(cC)
            h1, l1, c1 = cH[n - 3], cL[n - 3], cC[n - 3]
            o2, c2 = cO[n - 2], cC[n - 2]
            h3, l3 = cH[n - 1], cL[n - 1]
            acc_ok = (not p.use_acc) or (max(cH[n - 2 - p.acc_bars:n - 2]) - min(cL[n - 2 - p.acc_bars:n - 2])) <= p.acc_max_atr * atr5
            body_ok = abs(c2 - o2) >= p.brk_body * atr5
            gap = p.fvg_min_tk * tk
            bull = c2 > o2 and l3 - h1 >= gap
            bear = c2 < o2 and l1 - h3 >= gap
            lvl = None
            if p.allow_long and bull and body_ok and acc_ok:
                if p.use_ovn and not used["OH"] and ovnH is not None and c1 <= ovnH < c2:
                    lvl, used["OH"] = "Máx día", True
                elif p.use_prev and not used["PH"] and not math.isnan(prev_h[i]) and c1 <= prev_h[i] < c2:
                    lvl, used["PH"] = "Máx sesión ant.", True
                if lvl:
                    d, zTop, zBot = 1, l3, h1
            if lvl is None and p.allow_short and bear and body_ok and acc_ok:
                if p.use_ovn and not used["OL"] and ovnL is not None and c1 >= ovnL > c2:
                    lvl, used["OL"] = "Mín día", True
                elif p.use_prev and not used["PL"] and not math.isnan(prev_l[i]) and c1 >= prev_l[i] > c2:
                    lvl, used["PL"] = "Mín sesión ant.", True
                if lvl:
                    d, zTop, zBot = -1, l1, h3
            if lvl:
                st, cnt5, cnt1, ext, just_set, lvl_name = 1, 0, 0, None, True, lvl
                oTop.clear(); oBot.clear()

        # --- 2) seguimiento en M1
        if st > 0 and not just_set and i >= 2:
            if d == 1 and l[i - 2] - h[i] >= tk:
                oTop.append(l[i - 2]); oBot.append(h[i])
            if d == -1 and l[i] - h[i - 2] >= tk:
                oTop.append(l[i]); oBot.append(h[i - 2])

            if st == 1:
                touched = l[i] <= zTop if d == 1 else h[i] >= zBot
                if touched:
                    st, cnt1, ext = 2, 0, (l[i] if d == 1 else h[i])
                else:
                    for k in range(len(oTop) - 1, -1, -1):
                        if (d == 1 and c[i] > oTop[k]) or (d == -1 and c[i] < oBot[k]):
                            del oTop[k]; del oBot[k]
                if m5_closed:
                    cnt5 += 1
                    if cnt5 > p.wait_ret and st == 1:
                        cancel = True

            if st == 2:
                ext = min(ext, l[i]) if d == 1 else max(ext, h[i])
                sig = False
                for k in range(len(oTop) - 1, -1, -1):
                    tp_, bt_ = oTop[k], oBot[k]
                    if d == 1 and c[i] > tp_:
                        if c[i] > o[i] and o[i] <= tp_ and c[i] - o[i] >= p.ifvg_body * atr1[i]:
                            sig = True
                        del oTop[k]; del oBot[k]
                    elif d == -1 and c[i] < bt_:
                        if c[i] < o[i] and o[i] >= bt_ and o[i] - c[i] >= p.ifvg_body * atr1[i]:
                            sig = True
                        del oTop[k]; del oBot[k]
                if sig and in_trade and trades_today < p.max_trades and pos is None:
                    sl = ext - d * p.sl_buf_tk * tk
                    risk = abs(c[i] - sl)
                    if risk > 0:
                        entry = c[i] + d * slip
                        tp = c[i] + d * p.rr * risk
                        pos = Trade(idx[i], d, entry, sl, tp, lvl_name)
                        trades_today += 1
                        st = 0; oTop.clear(); oBot.clear()
                if st == 2:
                    cnt1 += 1
                    if cnt1 > p.wait_ent:
                        cancel = True

            if st > 0 and m5_closed:
                if (d == 1 and cC[-1] < zBot) or (d == -1 and cC[-1] > zTop):
                    cancel = True

        if st > 0 and not in_trade:
            cancel = True
        if cancel:
            st = 0; oTop.clear(); oBot.clear()

        prev_in_trade, prev_in_ovn = in_trade, in_ovn

    if pos is not None:
        _close(pos, idx[-1], c[-1], "Fin datos", p); trades.append(pos)
    return trades


def _close(t: Trade, when, px: float, why: str, p: Params) -> None:
    t.exit_time, t.exit, t.reason = when, px, why
    pts = (px - t.entry) * t.direction
    t.pnl = pts * p.point_value * p.qty - 2 * p.commission * p.qty
    risk = abs(t.entry - t.sl)
    t.r = pts / risk if risk else 0.0


def stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"trades": 0}
    pnl = pd.Series([t.pnl for t in trades])
    eq = pnl.cumsum()
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return {
        "trades": len(trades),
        "winrate_%": round(100 * (pnl > 0).mean(), 1),
        "net_$": round(pnl.sum(), 0),
        "pf": round(gp / gl, 2) if gl > 0 else float("inf"),
        "avg_R": round(pd.Series([t.r for t in trades]).mean(), 2),
        "max_dd_$": round((eq.cummax().clip(lower=0) - eq).max(), 0),
    }


if __name__ == "__main__":
    data = load_csv(sys.argv[1])
    tr = run(data, Params())
    print(stats(tr))
    pd.DataFrame([t.__dict__ for t in tr]).to_csv("trades.csv", index=False)
