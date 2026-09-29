# TrendEnsemblePortfolio (cBot para cTrader)

Versión para cTrader de la estrategia validada en `scripts/trend_strategies.py`:
conjunto de 4 cruces de EMAs, paridad de riesgo por activo y objetivo de
volatilidad de la cartera completa.

## Cómo funciona

Una vez al día, al cerrar la vela diaria:

1. **Señal por símbolo**: vota cada cruce de EMAs (8/32, 16/64, 32/128 y 64/256)
   sobre cierres diarios. La señal es la fracción de cruces alcistas: 0, 25, 50, 75
   o 100 %.
2. **Paridad de riesgo**: peso = señal × 15 % / volatilidad del símbolo (media
   exponencial de 32 días), dividido entre el número de símbolos. Los activos más
   volátiles reciben menos capital.
3. **Volatilidad de la cartera**: todos los pesos se escalan por un mismo factor para
   que la cartera ronde un 10 % de volatilidad anual, teniendo en cuenta cuánto se
   mueven juntos los activos. La exposición total nunca pasa de 1× el capital (con
   los valores por defecto).
4. **Ejecución**: cada posición solo se ajusta si se aleja del objetivo más que el
   umbral de rebalanceo. Las órdenes de un símbolo se envían cuando su mercado está
   abierto.

No usa stops por operación: el riesgo se controla con el tamaño. Como protección
extra, si la cuenta cae más de un 30 % desde su máximo, cierra todo y se detiene.

## Instalación

1. En cTrader, abre **Algo** → **cBots** → **New** y ponle un nombre.
2. Borra el código de ejemplo y pega el contenido de `TrendEnsemblePortfolio.cs`.
3. Pulsa **Build**. Debe compilar sin errores.
4. Añade una instancia en cualquier gráfico. El símbolo del gráfico solo importa si
   dejas vacío el parámetro "Símbolos".

## Parámetros principales

| Parámetro | Por defecto | Qué hace |
|---|---|---|
| Símbolos | vacío (símbolo del gráfico) | Lista separada por comas, con los nombres de tu bróker |
| Volatilidad objetivo por activo | 0,15 | Riesgo de cada activo antes de combinarlos |
| Volatilidad objetivo de la cartera | 0,10 | Riesgo anual buscado para toda la cartera |
| Exposición bruta máx. de la cartera | 1,0 | 1 = sin apalancamiento |
| Umbral de rebalanceo | 0,1 | Evita operar por cambios pequeños (se divide entre el nº de símbolos) |
| Parar si la caída supera (%) | 30 | Cierra todo y detiene el cBot |
| Solo simular en cuenta real | **Sí** | Registra lo que haría sin enviar órdenes. En backtest se ignora |

## Si no abre operaciones

Mira la pestaña **Log** del cBot. Siempre indica el motivo:

| Mensaje en el Log | Qué pasa | Solución |
|---|---|---|
| `MODO SIMULACIÓN: no se envían órdenes` | "Solo simular" está activado (cuenta real o demo) | Desactívalo cuando hayas revisado las señales |
| `Esperando historia: N días comunes…` | Aún no hay 300 días diarios comunes a todos los símbolos | En backtest, empieza al menos 15 meses después del inicio de los datos; si un símbolo tiene poca historia, quítalo |
| `…es menor que el volumen mínimo del bróker…` | Con tu capital, la posición calculada es más pequeña que el lote mínimo | Más capital o menos símbolos (cada uno recibe 1/N) |
| `Señal del …: US500 0,0 %, …` | Todas las señales están a 0: ninguna tendencia alcista | Es correcto: la estrategia está fuera del mercado |
| `Símbolo no encontrado…` | El nombre no coincide con el de tu bróker | Copia el nombre exacto de la lista de símbolos de cTrader |

Las órdenes de un símbolo se envían solo cuando su mercado está abierto. Si la
señal sale en fin de semana, se ejecutan al abrir.

## Qué símbolos usar

La estrategia solo funciona bien con **activos poco relacionados entre sí**. En el
backtest, sin bonos no mejoraba a comprar y mantener. Ejemplo con nombres habituales
en brókers de cTrader (comprueba los de tu bróker):

- Bolsa: `US500` (o `US30` / `GER40`; no pongas varios índices muy parecidos).
- Oro: `XAUUSD`.
- Petróleo: `XTIUSD` o `XBRUSD`.
- Divisas: `EURUSD`, `USDJPY`.
- Bonos, si tu bróker los tiene como CFD (por ejemplo `US10Y`, `BUND`). Son el
  activo que más aportó en el backtest.

## Antes de operar con dinero real

1. **Backtest en cTrader** con los datos de tu bróker, en velas diarias o *tick
   data*, desde 2015 o antes, con comisiones. Las versiones recientes de cTrader
   permiten backtest multisímbolo; si la tuya no, prueba cada símbolo por separado.
2. **Revisa los swaps (financiación nocturna).** Un CFD de índice en largo suele
   pagar el tipo de interés + ~2,5 % anual sobre el nominal. Con una exposición media
   del 70 % puede costar 1,5–2 puntos de rentabilidad al año. **El backtest de Python
   no lo incluye.** Mantener posiciones meses en CFDs es caro.
3. **Cuenta demo 1–3 meses**: primero con "Solo simular" activado, revisando el
   registro (*Log*), y después desactivado.
4. **Real con poco capital**. Con cuentas pequeñas, el volumen mínimo de algunos
   símbolos puede impedir ajustar los pesos con precisión.

## Resultados del backtest de Python (orientativos)

Fuera de muestra, 2002–2017, con S&P 500, Nasdaq, WTI y bono del Tesoro a 10 años,
costes del 0,1 % y efectivo al 1,22 %:

| | Rentab. anual | Sharpe | Caída máx. |
|---|---|---|---|
| Comprar y mantener 1/N | 7,9 % | 0,51 | 42,0 % |
| Esta estrategia (parámetros por defecto) | 7,0 % | 0,69 | 9,8 % |

Es un backtest con 4 activos en un periodo favorable a los bonos, con datos de
índices y no de CFDs. No garantiza resultados futuros.

## Verificación

`Verify/` compila el cBot contra el paquete oficial `cTrader.Automate` y calcula
los pesos con las mismas funciones que usa el cBot. Sobre los datos del backtest,
los pesos coinciden con los de Python (diferencia máxima 1e-16):

```bash
cd ctrader/Verify
dotnet run -- cierres.csv 300,800,1500 pesos_cbot.csv
```
