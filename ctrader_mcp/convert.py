from datetime import datetime, timezone

PRICE_SCALE = 100_000

PERIODS = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M10": 6, "M15": 7, "M30": 8,
    "H1": 9, "H4": 10, "H12": 11, "D1": 12, "W1": 13, "MN1": 14,
}

PERIOD_MINUTES = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M10": 10, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "H12": 720, "D1": 1440, "W1": 10080, "MN1": 43200,
}

TRADE_SIDES = {"BUY": 1, "SELL": 2}
ORDER_TYPES = {"MARKET": 1, "LIMIT": 2, "STOP": 3}
_ENUM_NAMES = {
    "tradeSide": {1: "BUY", 2: "SELL"},
    "orderType": {1: "MARKET", 2: "LIMIT", 3: "STOP", 4: "STOP_LOSS_TAKE_PROFIT",
                  5: "MARKET_RANGE", 6: "STOP_LIMIT"},
}


def enum_name(field, value):
    if isinstance(value, str):
        return value
    return _ENUM_NAMES.get(field, {}).get(value, value)


def normalize_symbol(name):
    return "".join(ch for ch in str(name).upper() if ch.isalnum())


def ms_to_iso(ms):
    if ms in (None, ""):
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()


def money(value, digits):
    if value is None:
        return None
    return int(value) / (10 ** int(digits or 2))


def trendbar_to_ohlc(bar, digits=5):
    low = int(bar.get("low", 0))
    return {
        "time": datetime.fromtimestamp(int(bar["utcTimestampInMinutes"]) * 60, tz=timezone.utc).isoformat(),
        "open": round((low + int(bar.get("deltaOpen", 0))) / PRICE_SCALE, digits),
        "high": round((low + int(bar.get("deltaHigh", 0))) / PRICE_SCALE, digits),
        "low": round(low / PRICE_SCALE, digits),
        "close": round((low + int(bar.get("deltaClose", 0))) / PRICE_SCALE, digits),
        "volume": int(bar.get("volume", 0)),
    }


def lots_to_volume(lots, lot_size, step_volume=None, min_volume=None, max_volume=None):
    """Convierte lotes a la unidad de volumen de cTrader (centésimas de unidad)."""
    if lots <= 0:
        raise ValueError("lots must be positive")
    volume = round(lots * int(lot_size))
    if step_volume:
        step = int(step_volume)
        volume = (volume // step) * step
    if min_volume and volume < int(min_volume):
        raise ValueError(f"volumen {volume} por debajo del mínimo {min_volume}")
    if max_volume and volume > int(max_volume):
        raise ValueError(f"volumen {volume} por encima del máximo {max_volume}")
    return volume


def volume_to_lots(volume, lot_size):
    return int(volume) / int(lot_size)


def pips_to_relative(pips, pip_position):
    """Distancia en pips -> distancia relativa en 1/100000 de precio (para órdenes a mercado)."""
    return int(round(pips * 10 ** (5 - int(pip_position))))


def position_summary(position, money_digits=2, symbol_names=None):
    trade = position.get("tradeData", {})
    digits = position.get("moneyDigits", money_digits)
    symbol_id = trade.get("symbolId")
    return {
        "positionId": position.get("positionId"),
        "symbolId": symbol_id,
        "symbol": (symbol_names or {}).get(int(symbol_id)) if symbol_id is not None else None,
        "side": enum_name("tradeSide", trade.get("tradeSide")),
        "units": int(trade.get("volume", 0)) / 100,
        "entryPrice": position.get("price"),
        "stopLoss": position.get("stopLoss"),
        "takeProfit": position.get("takeProfit"),
        "swap": money(position.get("swap"), digits),
        "commission": money(position.get("commission"), digits),
        "openTime": ms_to_iso(trade.get("openTimestamp")),
        "label": trade.get("label"),
        "comment": trade.get("comment"),
    }


def order_summary(order, symbol_names=None):
    trade = order.get("tradeData", {})
    symbol_id = trade.get("symbolId")
    return {
        "orderId": order.get("orderId"),
        "positionId": order.get("positionId"),
        "symbolId": symbol_id,
        "symbol": (symbol_names or {}).get(int(symbol_id)) if symbol_id is not None else None,
        "type": enum_name("orderType", order.get("orderType")),
        "side": enum_name("tradeSide", trade.get("tradeSide")),
        "units": int(trade.get("volume", 0)) / 100,
        "limitPrice": order.get("limitPrice"),
        "stopPrice": order.get("stopPrice"),
        "stopLoss": order.get("stopLoss"),
        "takeProfit": order.get("takeProfit"),
        "status": order.get("orderStatus"),
        "executionPrice": order.get("executionPrice"),
    }


def deal_summary(deal, symbol_names=None):
    digits = deal.get("moneyDigits", 2)
    symbol_id = deal.get("symbolId")
    close = deal.get("closePositionDetail") or {}
    return {
        "dealId": deal.get("dealId"),
        "positionId": deal.get("positionId"),
        "orderId": deal.get("orderId"),
        "symbol": (symbol_names or {}).get(int(symbol_id)) if symbol_id is not None else None,
        "side": enum_name("tradeSide", deal.get("tradeSide")),
        "units": int(deal.get("filledVolume", deal.get("volume", 0))) / 100,
        "price": deal.get("executionPrice"),
        "time": ms_to_iso(deal.get("executionTimestamp")),
        "commission": money(deal.get("commission"), digits),
        "closing": bool(close),
        "grossProfit": money(close.get("grossProfit"), close.get("moneyDigits", digits)) if close else None,
        "swap": money(close.get("swap"), close.get("moneyDigits", digits)) if close else None,
    }
