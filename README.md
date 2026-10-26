# claude-scripts-trading

Colección de pequeños scripts de utilidad para análisis de trading, desarrollados con ayuda de Claude.

## Contenido

- `scripts/moving_average.py`: cálculo de medias móviles simples sobre una serie de precios.
- `scripts/choch_fvg.py`: indicadores de estructura de mercado:
  - `find_fvgs`: Fair Value Gaps (alcistas/bajistas) con vela de mitigación e inversión.
  - `find_ifvgs`: Inverse FVG, creados cuando una vela cierra al otro lado de un FVG.
  - `find_structure_breaks` / `find_choch`: rupturas de estructura (BOS) y Change of Character (CHoCH) a partir de swings confirmados, sin mirar al futuro.
- `pine/choch_fvg_ifvg.pine`: indicador de TradingView que **marca en el gráfico** CHoCH/BOS (línea + etiqueta), FVG (cajas) e IFVG (caja nueva al invertirse), con alertas para cada evento. Copiar el contenido en el editor de Pine y pulsar «Añadir al gráfico».

- `pine/choch_pro_fvg_ifvg.pine`: indicador principal de TradingView **«Po3 + CHoCH PRO - High Contrast + FVG + Rangos + OB»** (Pine v6): CHoCH/BOS sin repintado, FVG e IFVG del gráfico y de M15/H1/H4 con consumo progresivo, Order Blocks, rangos (Auto Range Detector de QuantAlgo, CC BY-NC-SA 4.0), EMAs 9/20/200, horas de la apertura de Nueva York, niveles clave y alertas (incluido el retesteo de IFVG).
- `docs/estrategia/`: documento de la estrategia de apertura de Nueva York (Bias + PO3) y sus gráficos.

## Uso

```bash
python -c "from scripts.moving_average import simple_moving_average; print(simple_moving_average([1,2,3,4,5], 3))"
```

```python
from scripts.choch_fvg import find_fvgs, find_ifvgs, find_choch

fvgs = find_fvgs(highs, lows, closes=closes)
ifvgs = find_ifvgs(highs, lows, closes)
chochs = find_choch(highs, lows, closes, swing_length=5)
```

## Tests

```bash
pytest
```
