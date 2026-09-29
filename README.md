# claude-scripts-trading

Colección de pequeños scripts de utilidad para análisis de trading, desarrollados con ayuda de Claude.

## Contenido

- `scripts/moving_average.py`: cálculo de medias móviles simples sobre una serie de precios.
- `ctrader_mcp/`: servidor MCP que conecta Claude con cTrader a través de la cTrader Open API.

## Uso

```bash
python -c "from scripts.moving_average import simple_moving_average; print(simple_moving_average([1,2,3,4,5], 3))"
```

## Tests

```bash
pytest
```

## Conectar cTrader con Claude (servidor MCP)

`ctrader_mcp` es un servidor [MCP](https://modelcontextprotocol.io) que habla con la
cTrader Open API (JSON sobre WebSocket) y expone estas herramientas a Claude:

| Herramienta | Qué hace |
|---|---|
| `list_accounts` | Cuentas autorizadas por el token |
| `get_account` | Balance, apalancamiento, broker |
| `get_positions` | Posiciones abiertas y órdenes pendientes |
| `search_symbols` / `get_symbol_info` | Buscar símbolos y ver lote, pip, límites |
| `get_price_bars` | Velas OHLC históricas (M1 … MN1) |
| `get_deals` | Historial de ejecuciones con P&L |
| `place_order` | Orden MARKET / LIMIT / STOP con SL/TP * |
| `close_position` | Cierre total o parcial * |
| `modify_position` | Cambiar SL/TP * |
| `cancel_order` | Cancelar orden pendiente * |
| `server_status` | Configuración activa |

\* Solo funcionan con `CTRADER_ALLOW_TRADING=1`. Por defecto el servidor es de solo lectura.

### 1. Instalar

```bash
pip install -r requirements.txt
```

### 2. Crear una aplicación en cTrader Open API

1. Entra en <https://openapi.ctrader.com/apps> con tu cTrader ID y crea una aplicación.
2. Añade `http://localhost:8765/callback` como *Redirect URI*.
3. Espera a que la aplicación esté activa y copia el **Client ID** y el **Client Secret**.

### 3. Obtener el access token

```bash
python -m ctrader_mcp.auth login --client-id TU_ID --client-secret TU_SECRET
```

Se abre el navegador; autoriza las cuentas y el script imprime `CTRADER_ACCESS_TOKEN` y
`CTRADER_REFRESH_TOKEN`. El token caduca (~30 días); renuévalo con:

```bash
python -m ctrader_mcp.auth refresh --client-id TU_ID --client-secret TU_SECRET --refresh-token TU_REFRESH
```

### 4. Registrar el servidor en Claude

**Claude Code** (desde la raíz del repo):

```bash
claude mcp add ctrader \
  -e CTRADER_CLIENT_ID=TU_ID -e CTRADER_CLIENT_SECRET=TU_SECRET \
  -e CTRADER_ACCESS_TOKEN=TU_TOKEN -e CTRADER_HOST=demo \
  -- python -m ctrader_mcp
```

**Claude Desktop**: copia el bloque de `.mcp.json.example` dentro de
`claude_desktop_config.json` (Ajustes → Desarrollador → Editar configuración), ajusta
`cwd` a la ruta del repo y reinicia Claude.

### Variables de entorno

| Variable | Descripción |
|---|---|
| `CTRADER_CLIENT_ID` / `CTRADER_CLIENT_SECRET` | Credenciales de la aplicación Open API |
| `CTRADER_ACCESS_TOKEN` | Token OAuth obtenido en el paso 3 |
| `CTRADER_HOST` | `demo` (por defecto) o `live` |
| `CTRADER_ACCOUNT_ID` | ctidTraderAccountId por defecto (opcional; si falta se usa la primera cuenta del host) |
| `CTRADER_ALLOW_TRADING` | `1` para permitir enviar/cerrar/modificar órdenes |

Recomendación: prueba primero con `CTRADER_HOST=demo` y una cuenta demo antes de habilitar
trading en real.
