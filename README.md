# claude-scripts-trading

Colección de pequeños scripts de utilidad para análisis de trading, desarrollados con ayuda de Claude.

## Contenido

- `scripts/moving_average.py`: cálculo de medias móviles simples sobre una serie de precios.
- `scripts/trend_strategies.py`: tres estrategias tendenciales con backtest, cortos opcionales, tamaño por ATR y walk-forward:
  - `ma_crossover`: EMA 20/50 + filtro SMA 200 + stop dinámico de 3×ATR.
  - `donchian`: ruptura del máximo de 20 barras, salida en el mínimo de 10 (tipo Turtle).
  - `supertrend_adx`: Supertrend (10, 3) con ADX(14) > 25 y subiendo + Chandelier Exit (22, 3×ATR).

## Uso

```bash
python -c "from scripts.moving_average import simple_moving_average; print(simple_moving_average([1,2,3,4,5], 3))"

# Backtest de las estrategias tendenciales sobre un CSV (columnas high, low, close)
python -m scripts.trend_strategies datos.csv --strategy all --cost 0.001

# Probar con datos sintéticos
python -m scripts.trend_strategies --demo

# Con cortos y tamaño por ATR (arriesga el 1 % por operación con stop de 2×ATR)
python -m scripts.trend_strategies --demo --short --risk 0.01

# Walk-forward: optimiza en 756 barras, evalúa en las 252 siguientes y avanza
python -m scripts.trend_strategies --demo --walk-forward --train 756 --test 252
```

- `--short`: las estrategias también abren cortos (reglas simétricas) y pueden
  girar directamente de largo a corto.
- `--risk R`: tamaño = R / (stop-mult × ATR / precio), fijado al abrir cada
  operación y limitado por `--max-leverage` (1 por defecto).
- `--walk-forward`: en cada bloque elige los parámetros de `PARAM_GRIDS` con mejor
  `--objective` (sharpe por defecto) en la ventana de entrenamiento y los aplica
  al bloque siguiente. Las métricas mostradas son solo las de fuera de muestra.

Las señales se calculan al cierre de cada barra y se aplican a la barra siguiente
(sin lookahead). `--cost` es comisión + slippage por lado.

## Tests

```bash
pytest
```
