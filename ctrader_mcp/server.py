import os
import time
from datetime import datetime, timezone

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from . import client as api
from .client import CTraderClient
from .convert import (
    ORDER_TYPES, PERIOD_MINUTES, PERIODS, TRADE_SIDES, deal_summary, lots_to_volume, money,
    normalize_symbol, order_summary, pips_to_relative, position_summary, trendbar_to_ohlc,
    volume_to_lots,
)

FILLED_OR_REJECTED = {3, 7, "ORDER_FILLED", "ORDER_REJECTED"}

mcp = MCPServer(
    "ctrader",
    instructions=(
        "Acceso a una cuenta de cTrader mediante la Open API: cuenta, posiciones, símbolos, "
        "velas históricas, historial de operaciones y (si CTRADER_ALLOW_TRADING=1) envío de órdenes. "
        "Antes de enviar, modificar o cerrar una orden, confirma siempre los detalles con el usuario."
    ),
)


class State:
    def __init__(self):
        self.client = None
        self.default_account = None
        self.symbols = {}
        self.symbol_details = {}

    def get_client(self):
        if self.client is None:
            missing = [k for k in ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN")
                       if not os.environ.get(k)]
            if missing:
                raise RuntimeError(f"faltan variables de entorno: {', '.join(missing)}")
            self.client = CTraderClient(
                os.environ["CTRADER_CLIENT_ID"],
                os.environ["CTRADER_CLIENT_SECRET"],
                os.environ["CTRADER_ACCESS_TOKEN"],
                host=os.environ.get("CTRADER_HOST", "demo"),
            )
        return self.client


state = State()


def _trading_enabled():
    return os.environ.get("CTRADER_ALLOW_TRADING", "").lower() in ("1", "true", "yes", "si", "sí")


def _require_trading():
    if not _trading_enabled():
        raise RuntimeError("el trading está desactivado; define CTRADER_ALLOW_TRADING=1 para habilitarlo")


async def _accounts():
    body = await state.get_client().request(
        api.GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ, {"accessToken": state.get_client().access_token})
    return body.get("ctidTraderAccount", [])


async def _account_id(account_id=None):
    if account_id:
        return int(account_id)
    if os.environ.get("CTRADER_ACCOUNT_ID"):
        return int(os.environ["CTRADER_ACCOUNT_ID"])
    if state.default_account is None:
        want_live = os.environ.get("CTRADER_HOST", "demo") == "live"
        accounts = await _accounts()
        matching = [a for a in accounts if bool(a.get("isLive")) == want_live]
        if not matching:
            raise RuntimeError("no hay cuentas disponibles para este token y host")
        state.default_account = int(matching[0]["ctidTraderAccountId"])
    return state.default_account


async def _symbol_names(account):
    if account not in state.symbols:
        body = await state.get_client().account_request(account, api.SYMBOLS_LIST_REQ)
        state.symbols[account] = {int(s["symbolId"]): s.get("symbolName", "") for s in body.get("symbol", [])}
    return state.symbols[account]


async def _resolve_symbol(account, symbol):
    names = await _symbol_names(account)
    if str(symbol).isdigit() and int(symbol) in names:
        return int(symbol)
    wanted = normalize_symbol(symbol)
    for symbol_id, name in names.items():
        if normalize_symbol(name) == wanted:
            return symbol_id
    raise ValueError(f"símbolo no encontrado: {symbol}")


async def _symbol_detail(account, symbol_id):
    key = (account, symbol_id)
    if key not in state.symbol_details:
        body = await state.get_client().account_request(
            account, api.SYMBOL_BY_ID_REQ, {"symbolId": [symbol_id]})
        symbols = body.get("symbol", [])
        if not symbols:
            raise ValueError(f"sin detalles para el símbolo {symbol_id}")
        state.symbol_details[key] = symbols[0]
    return state.symbol_details[key]


def _execution_result(body, names):
    result = {"executionType": body.get("executionType")}
    if body.get("position"):
        result["position"] = position_summary(body["position"], symbol_names=names)
    if body.get("order"):
        result["order"] = order_summary(body["order"], symbol_names=names)
    if body.get("errorCode"):
        result["errorCode"] = body["errorCode"]
    return result


@mcp.tool()
async def list_accounts() -> list[dict]:
    """Lista las cuentas de cTrader autorizadas por el token de acceso."""
    return [
        {
            "accountId": a.get("ctidTraderAccountId"),
            "login": a.get("traderLogin"),
            "isLive": bool(a.get("isLive")),
        }
        for a in await _accounts()
    ]


@mcp.tool()
async def get_account(account_id: int | None = None) -> dict:
    """Devuelve balance, apalancamiento, broker y datos básicos de la cuenta."""
    account = await _account_id(account_id)
    trader = (await state.get_client().account_request(account, api.TRADER_REQ)).get("trader", {})
    digits = trader.get("moneyDigits", 2)
    leverage = trader.get("leverageInCents")
    return {
        "accountId": account,
        "login": trader.get("traderLogin"),
        "broker": trader.get("brokerName"),
        "balance": money(trader.get("balance"), digits),
        "leverage": int(leverage) / 100 if leverage else None,
        "accountType": trader.get("accountType"),
        "accessRights": trader.get("accessRights"),
    }


@mcp.tool()
async def get_positions(account_id: int | None = None) -> dict:
    """Devuelve las posiciones abiertas y las órdenes pendientes de la cuenta."""
    account = await _account_id(account_id)
    body = await state.get_client().account_request(account, api.RECONCILE_REQ)
    names = await _symbol_names(account)
    return {
        "positions": [position_summary(p, symbol_names=names) for p in body.get("position", [])],
        "orders": [order_summary(o, symbol_names=names) for o in body.get("order", [])],
    }


@mcp.tool()
async def search_symbols(query: str = "", limit: int = 50, account_id: int | None = None) -> list[dict]:
    """Busca símbolos negociables por nombre (p. ej. 'EUR', 'XAU', 'US500')."""
    account = await _account_id(account_id)
    names = await _symbol_names(account)
    wanted = normalize_symbol(query)
    found = [{"symbolId": i, "symbol": n} for i, n in names.items() if wanted in normalize_symbol(n)]
    return sorted(found, key=lambda s: (len(s["symbol"]), s["symbol"]))[:limit]


@mcp.tool()
async def get_symbol_info(symbol: str, account_id: int | None = None) -> dict:
    """Devuelve dígitos, tamaño de pip, tamaño de lote y límites de volumen de un símbolo."""
    account = await _account_id(account_id)
    symbol_id = await _resolve_symbol(account, symbol)
    detail = await _symbol_detail(account, symbol_id)
    lot_size = int(detail.get("lotSize", 10_000_000))
    return {
        "symbolId": symbol_id,
        "symbol": (await _symbol_names(account))[symbol_id],
        "digits": detail.get("digits"),
        "pipPosition": detail.get("pipPosition"),
        "lotSizeUnits": lot_size / 100,
        "minLots": volume_to_lots(detail.get("minVolume", 0), lot_size),
        "maxLots": volume_to_lots(detail.get("maxVolume", 0), lot_size),
        "stepLots": volume_to_lots(detail.get("stepVolume", 0), lot_size),
        "swapLong": detail.get("swapLong"),
        "swapShort": detail.get("swapShort"),
    }


@mcp.tool()
async def get_price_bars(symbol: str, timeframe: str = "H1", count: int = 100,
                         account_id: int | None = None) -> dict:
    """Devuelve velas OHLC (bid) recientes. timeframe: M1, M5, M15, M30, H1, H4, D1, W1, MN1..."""
    timeframe = timeframe.upper()
    if timeframe not in PERIODS:
        raise ValueError(f"timeframe no válido: {timeframe}; usa uno de {', '.join(PERIODS)}")
    count = max(1, min(int(count), 5000))
    account = await _account_id(account_id)
    symbol_id = await _resolve_symbol(account, symbol)
    detail = await _symbol_detail(account, symbol_id)
    now_ms = int(time.time() * 1000)
    span_ms = PERIOD_MINUTES[timeframe] * 60_000 * count * 3 + 7 * 86_400_000
    body = await state.get_client().account_request(account, api.GET_TRENDBARS_REQ, {
        "fromTimestamp": now_ms - span_ms,
        "toTimestamp": now_ms,
        "period": PERIODS[timeframe],
        "symbolId": symbol_id,
    })
    digits = int(detail.get("digits", 5))
    bars = [trendbar_to_ohlc(b, digits) for b in body.get("trendbar", [])]
    bars.sort(key=lambda b: b["time"])
    return {"symbol": (await _symbol_names(account))[symbol_id], "timeframe": timeframe, "bars": bars[-count:]}


@mcp.tool()
async def get_deals(days: int = 7, max_rows: int = 200, account_id: int | None = None) -> list[dict]:
    """Devuelve el historial de ejecuciones (deals) de los últimos días, incluido el P&L de cierres."""
    account = await _account_id(account_id)
    now_ms = int(time.time() * 1000)
    body = await state.get_client().account_request(account, api.DEAL_LIST_REQ, {
        "fromTimestamp": now_ms - int(days) * 86_400_000,
        "toTimestamp": now_ms,
        "maxRows": int(max_rows),
    })
    names = await _symbol_names(account)
    return [deal_summary(d, symbol_names=names) for d in body.get("deal", [])]


@mcp.tool()
async def place_order(symbol: str, side: str, lots: float, order_type: str = "MARKET",
                      price: float | None = None,
                      stop_loss_pips: float | None = None, take_profit_pips: float | None = None,
                      stop_loss: float | None = None, take_profit: float | None = None,
                      label: str | None = None, comment: str | None = None,
                      account_id: int | None = None) -> dict:
    """Envía una orden. side: BUY/SELL. order_type: MARKET, LIMIT o STOP (estas dos requieren price).
    Para MARKET usa stop_loss_pips/take_profit_pips; para LIMIT/STOP también se admiten precios absolutos
    stop_loss/take_profit. Requiere CTRADER_ALLOW_TRADING=1. Confirma siempre con el usuario antes."""
    _require_trading()
    side, order_type = side.upper(), order_type.upper()
    if side not in TRADE_SIDES:
        raise ValueError("side debe ser BUY o SELL")
    if order_type not in ORDER_TYPES:
        raise ValueError("order_type debe ser MARKET, LIMIT o STOP")
    if order_type != "MARKET" and price is None:
        raise ValueError(f"una orden {order_type} requiere price")
    if order_type == "MARKET" and (stop_loss is not None or take_profit is not None):
        raise ValueError("en órdenes MARKET usa stop_loss_pips/take_profit_pips")

    account = await _account_id(account_id)
    symbol_id = await _resolve_symbol(account, symbol)
    detail = await _symbol_detail(account, symbol_id)
    volume = lots_to_volume(lots, detail.get("lotSize", 10_000_000), detail.get("stepVolume"),
                            detail.get("minVolume"), detail.get("maxVolume"))
    pip_position = int(detail.get("pipPosition", 4))

    payload = {"symbolId": symbol_id, "orderType": ORDER_TYPES[order_type],
               "tradeSide": TRADE_SIDES[side], "volume": volume}
    if order_type == "LIMIT":
        payload["limitPrice"] = price
    elif order_type == "STOP":
        payload["stopPrice"] = price
    if stop_loss_pips is not None:
        payload["relativeStopLoss"] = pips_to_relative(stop_loss_pips, pip_position)
    if take_profit_pips is not None:
        payload["relativeTakeProfit"] = pips_to_relative(take_profit_pips, pip_position)
    if stop_loss is not None:
        payload["stopLoss"] = stop_loss
    if take_profit is not None:
        payload["takeProfit"] = take_profit
    if label:
        payload["label"] = label[:100]
    if comment:
        payload["comment"] = comment[:512]

    until = (lambda m: m.get("payload", {}).get("executionType") in FILLED_OR_REJECTED) \
        if order_type == "MARKET" else None
    body = await state.get_client().account_request(account, api.NEW_ORDER_REQ, payload, until)
    return _execution_result(body, await _symbol_names(account))


@mcp.tool()
async def close_position(position_id: int, lots: float | None = None, account_id: int | None = None) -> dict:
    """Cierra una posición (entera, o parcialmente si se indica lots). Requiere CTRADER_ALLOW_TRADING=1."""
    _require_trading()
    account = await _account_id(account_id)
    positions = (await state.get_client().account_request(account, api.RECONCILE_REQ)).get("position", [])
    position = next((p for p in positions if int(p["positionId"]) == int(position_id)), None)
    if position is None:
        raise ValueError(f"posición {position_id} no encontrada")
    volume = int(position["tradeData"]["volume"])
    if lots is not None:
        detail = await _symbol_detail(account, int(position["tradeData"]["symbolId"]))
        volume = min(volume, lots_to_volume(lots, detail.get("lotSize", 10_000_000), detail.get("stepVolume")))
    body = await state.get_client().account_request(
        account, api.CLOSE_POSITION_REQ, {"positionId": int(position_id), "volume": volume},
        lambda m: m.get("payload", {}).get("executionType") in FILLED_OR_REJECTED)
    return _execution_result(body, await _symbol_names(account))


@mcp.tool()
async def modify_position(position_id: int, stop_loss: float | None = None, take_profit: float | None = None,
                          account_id: int | None = None) -> dict:
    """Cambia el stop loss y/o take profit (precios absolutos) de una posición. Requiere CTRADER_ALLOW_TRADING=1."""
    _require_trading()
    if stop_loss is None and take_profit is None:
        raise ValueError("indica stop_loss y/o take_profit")
    account = await _account_id(account_id)
    positions = (await state.get_client().account_request(account, api.RECONCILE_REQ)).get("position", [])
    position = next((p for p in positions if int(p["positionId"]) == int(position_id)), None)
    if position is None:
        raise ValueError(f"posición {position_id} no encontrada")
    payload = {"positionId": int(position_id)}
    stop_loss = stop_loss if stop_loss is not None else position.get("stopLoss")
    take_profit = take_profit if take_profit is not None else position.get("takeProfit")
    if stop_loss is not None:
        payload["stopLoss"] = stop_loss
    if take_profit is not None:
        payload["takeProfit"] = take_profit
    body = await state.get_client().account_request(account, api.AMEND_POSITION_SLTP_REQ, payload)
    return _execution_result(body, await _symbol_names(account))


@mcp.tool()
async def cancel_order(order_id: int, account_id: int | None = None) -> dict:
    """Cancela una orden pendiente. Requiere CTRADER_ALLOW_TRADING=1."""
    _require_trading()
    account = await _account_id(account_id)
    body = await state.get_client().account_request(account, api.CANCEL_ORDER_REQ, {"orderId": int(order_id)})
    return _execution_result(body, await _symbol_names(account))


@mcp.tool()
async def server_status() -> dict:
    """Muestra la configuración activa (host, cuenta por defecto, trading habilitado)."""
    return {
        "host": os.environ.get("CTRADER_HOST", "demo"),
        "defaultAccount": os.environ.get("CTRADER_ACCOUNT_ID") or state.default_account,
        "tradingEnabled": _trading_enabled(),
        "connected": state.client is not None and state.client.connected,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def main():
    mcp.run()


if __name__ == "__main__":
    main()
