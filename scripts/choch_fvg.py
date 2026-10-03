"""Indicadores de estructura de mercado: CHoCH (Change of Character), FVG (Fair Value Gap)
e IFVG (Inverse Fair Value Gap).

Todas las funciones reciben listas paralelas de precios (highs, lows, closes)
ordenadas de la vela más antigua a la más reciente, y no miran al futuro:
un evento en el índice ``i`` solo usa información disponible al cierre de ``i``.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class FairValueGap:
    index: int                # vela que completa el patrón de 3 velas
    direction: str            # "bullish" o "bearish"
    top: float
    bottom: float
    mitigated_index: Optional[int] = None  # vela que rellena el gap por completo
    inverted_index: Optional[int] = None   # vela que cierra al otro lado (crea un IFVG)


@dataclass
class InverseFairValueGap:
    index: int                # vela cuyo cierre invierte el FVG (creación del IFVG)
    direction: str            # polaridad nueva: "bullish" (soporte) o "bearish" (resistencia)
    top: float
    bottom: float
    source_index: int         # índice del FVG original


@dataclass
class StructureBreak:
    index: int                # vela cuyo cierre rompe el swing
    kind: str                 # "CHoCH" o "BOS"
    direction: str            # "bullish" o "bearish"
    level: float              # precio del swing roto
    swing_index: int          # vela donde se formó el swing


def _check_lengths(*series):
    if len({len(s) for s in series}) > 1:
        raise ValueError("highs, lows and closes must have the same length")


def find_fvgs(highs, lows, min_size=0.0, closes=None):
    """Detecta Fair Value Gaps de 3 velas.

    - Alcista: ``low[i] > high[i-2]``  -> gap entre high[i-2] y low[i].
    - Bajista: ``high[i] < low[i-2]``  -> gap entre high[i] y low[i-2].

    Un gap queda mitigado cuando una vela posterior lo atraviesa por completo
    (low <= bottom en uno alcista, high >= top en uno bajista). Si se pasan
    ``closes``, además se rellena ``inverted_index``: la primera vela que
    cierra al otro lado del gap (close < bottom en uno alcista, close > top
    en uno bajista).
    """
    _check_lengths(highs, lows, *([closes] if closes is not None else []))
    if min_size < 0:
        raise ValueError("min_size must be non-negative")

    gaps: List[FairValueGap] = []
    for i in range(2, len(highs)):
        if lows[i] > highs[i - 2] and lows[i] - highs[i - 2] > min_size:
            gaps.append(FairValueGap(i, "bullish", lows[i], highs[i - 2]))
        elif highs[i] < lows[i - 2] and lows[i - 2] - highs[i] > min_size:
            gaps.append(FairValueGap(i, "bearish", lows[i - 2], highs[i]))

    for gap in gaps:
        for j in range(gap.index + 1, len(highs)):
            if (gap.direction == "bullish" and lows[j] <= gap.bottom) or (
                gap.direction == "bearish" and highs[j] >= gap.top
            ):
                gap.mitigated_index = j
                break
        if closes is not None:
            for j in range(gap.index + 1, len(closes)):
                if (gap.direction == "bullish" and closes[j] < gap.bottom) or (
                    gap.direction == "bearish" and closes[j] > gap.top
                ):
                    gap.inverted_index = j
                    break
    return gaps


def find_ifvgs(highs, lows, closes, min_size=0.0):
    """Detecta Inverse Fair Value Gaps, ordenados por vela de creación.

    Un FVG alcista que recibe un cierre por debajo de su ``bottom`` se convierte
    en un IFVG bajista (zona de resistencia); un FVG bajista que recibe un cierre
    por encima de su ``top`` se convierte en un IFVG alcista (zona de soporte).
    """
    ifvgs = [
        InverseFairValueGap(
            gap.inverted_index,
            "bearish" if gap.direction == "bullish" else "bullish",
            gap.top,
            gap.bottom,
            gap.index,
        )
        for gap in find_fvgs(highs, lows, min_size, closes)
        if gap.inverted_index is not None
    ]
    return sorted(ifvgs, key=lambda g: (g.index, g.source_index))


def find_swings(highs, lows, length):
    """Devuelve (swing_highs, swing_lows) como listas de (índice, precio).

    Un pivote en ``p`` requiere ``length`` velas a cada lado con máximos
    (o mínimos) estrictamente menores (mayores); se confirma en ``p + length``.
    """
    _check_lengths(highs, lows)
    if length <= 0:
        raise ValueError("length must be positive")

    swing_highs, swing_lows = [], []
    for p in range(length, len(highs) - length):
        neighbours = list(range(p - length, p)) + list(range(p + 1, p + length + 1))
        if all(highs[p] > highs[k] for k in neighbours):
            swing_highs.append((p, highs[p]))
        if all(lows[p] < lows[k] for k in neighbours):
            swing_lows.append((p, lows[p]))
    return swing_highs, swing_lows


def find_structure_breaks(highs, lows, closes, swing_length=5):
    """Detecta rupturas de estructura (BOS) y cambios de carácter (CHoCH).

    Un cierre por encima del último swing high confirmado es una ruptura
    alcista; por debajo del último swing low, bajista. Si la ruptura va en
    contra de la tendencia vigente es un CHoCH; si va a favor, un BOS. La
    primera ruptura de la serie solo fija la tendencia y se marca como BOS.
    Cada swing se puede romper una sola vez.
    """
    _check_lengths(highs, lows, closes)
    swing_highs, swing_lows = find_swings(highs, lows, swing_length)

    events: List[StructureBreak] = []
    trend = None
    last_high = last_low = None  # (índice, precio) del swing vigente sin romper
    hi_ptr = lo_ptr = 0

    for i in range(len(closes)):
        # Incorporar los swings que quedan confirmados en esta vela.
        while hi_ptr < len(swing_highs) and swing_highs[hi_ptr][0] + swing_length <= i:
            last_high = swing_highs[hi_ptr]
            hi_ptr += 1
        while lo_ptr < len(swing_lows) and swing_lows[lo_ptr][0] + swing_length <= i:
            last_low = swing_lows[lo_ptr]
            lo_ptr += 1

        if last_high is not None and closes[i] > last_high[1]:
            kind = "CHoCH" if trend == "bearish" else "BOS"
            events.append(StructureBreak(i, kind, "bullish", last_high[1], last_high[0]))
            trend = "bullish"
            last_high = None
        elif last_low is not None and closes[i] < last_low[1]:
            kind = "CHoCH" if trend == "bullish" else "BOS"
            events.append(StructureBreak(i, kind, "bearish", last_low[1], last_low[0]))
            trend = "bearish"
            last_low = None
    return events


def find_choch(highs, lows, closes, swing_length=5):
    """Atajo que devuelve solo los eventos CHoCH."""
    return [
        e for e in find_structure_breaks(highs, lows, closes, swing_length)
        if e.kind == "CHoCH"
    ]
