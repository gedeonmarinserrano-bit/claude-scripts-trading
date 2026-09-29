# claude-scripts-trading

Colección de pequeños scripts de utilidad para análisis de trading, desarrollados con ayuda de Claude.

## Contenido

- `scripts/moving_average.py`: cálculo de medias móviles simples sobre una serie de precios.
- `scripts/trend_strategies.py`: tres estrategias tendenciales con backtest, cortos opcionales, tamaño por ATR, walk-forward, intereses del efectivo y carteras:
  - `ma_crossover`: EMA 20/50 + filtro SMA 200 + stop dinámico de 3×ATR.
  - `donchian`: ruptura del máximo de 20 barras, salida en el mínimo de 10 (tipo Turtle).
  - `supertrend_adx`: Supertrend (10, 3) con ADX(14) > 25 y subiendo + Chandelier Exit (22, 3×ATR).
  - `trend_ensemble`: media de 4 cruces de EMAs (8/32, 16/64, 32/128, 64/256); la posición
    es la fracción de pares alcistas. Sin stops ni optimización; pensada para usarse con
    `--vol-target`. Es la versión recomendada.

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

# Estrategia recomendada: conjunto de cruces con objetivo de volatilidad del 15 %
python -m scripts.trend_strategies spx.csv --strategy trend_ensemble --vol-target 0.15 --cash-rate 0.02

# Cartera de varios activos (un CSV por activo) con un 2 % anual para el efectivo
python -m scripts.trend_strategies spx.csv ndx.csv wti.csv --cash-rate 0.02 --walk-forward
```

- `--short`: las estrategias también abren cortos (reglas simétricas) y pueden
  girar directamente de largo a corto.
- `--risk R`: tamaño = R / (stop-mult × ATR / precio), fijado al abrir cada
  operación y limitado por `--max-leverage` (1 por defecto).
- `--walk-forward`: en cada bloque elige los parámetros de `PARAM_GRIDS` con mejor
  `--objective` (sharpe por defecto) en la ventana de entrenamiento y los aplica
  al bloque siguiente. Las métricas mostradas son solo las de fuera de muestra.
- `--vol-target V`: exposición = señal × V / volatilidad reciente (media exponencial de
  `--vol-span` barras), limitada por `--max-leverage`; solo se rebalancea si la exposición
  cambia al menos `--rebalance-buffer` (0,1 por defecto). Excluye `--risk`.
- `--cash-rate R`: el efectivo no invertido en largos cobra R anual (los cortos no
  consumen efectivo; el apalancamiento por encima del 100 % paga R). El Sharpe se
  calcula sobre la rentabilidad en exceso de R.
- Varios CSV: cartera en las fechas comunes a todos (el CSV necesita columna
  `date`). Sin `--risk`, cada activo recibe 1/N del capital; con `--risk`, cada
  operación arriesga R del capital total. Se muestran la cartera y cada activo.
- Los CSV solo necesitan `close` (o `adj close`); sin `high`/`low` se usa el cierre.
  Las filas no numéricas (`null`, `.`) se ignoran.

Las señales se calculan al cierre de cada barra y se aplican a la barra siguiente
(sin lookahead). `--cost` es comisión + slippage por lado.

## Tests

```bash
pytest
```
