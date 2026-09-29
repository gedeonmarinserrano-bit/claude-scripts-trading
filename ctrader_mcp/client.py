import asyncio
import itertools
import json
import logging

import websockets

log = logging.getLogger(__name__)

HOSTS = {
    "demo": "wss://demo.ctraderapi.com:5036",
    "live": "wss://live.ctraderapi.com:5036",
}

ERROR_RES = 50
HEARTBEAT_EVENT = 51
APPLICATION_AUTH_REQ = 2100
ACCOUNT_AUTH_REQ = 2102
NEW_ORDER_REQ = 2106
CANCEL_ORDER_REQ = 2108
AMEND_POSITION_SLTP_REQ = 2110
CLOSE_POSITION_REQ = 2111
SYMBOLS_LIST_REQ = 2114
SYMBOL_BY_ID_REQ = 2116
TRADER_REQ = 2121
RECONCILE_REQ = 2124
EXECUTION_EVENT = 2126
ORDER_ERROR_EVENT = 2132
DEAL_LIST_REQ = 2133
GET_TRENDBARS_REQ = 2137
OA_ERROR_RES = 2142
GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ = 2149

ERROR_TYPES = {ERROR_RES, OA_ERROR_RES, ORDER_ERROR_EVENT}


class CTraderError(Exception):
    def __init__(self, code, description=""):
        super().__init__(f"{code}: {description}" if description else str(code))
        self.code = code
        self.description = description


class CTraderClient:
    """Cliente asíncrono de la cTrader Open API usando JSON sobre WebSocket."""

    def __init__(self, client_id, client_secret, access_token, host="demo",
                 timeout=15.0, heartbeat_interval=10.0):
        self.url = HOSTS.get(host, host)
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.timeout = timeout
        self.heartbeat_interval = heartbeat_interval
        self._ws = None
        self._ids = itertools.count(1)
        self._pending = {}
        self._authorized_accounts = set()
        self._reader_task = None
        self._heartbeat_task = None
        self._lock = asyncio.Lock()
        self._account_lock = asyncio.Lock()

    @property
    def connected(self):
        return self._ws is not None and self._reader_task is not None and not self._reader_task.done()

    async def connect(self):
        async with self._lock:
            if self.connected:
                return
            await self._close_transport()
            self._ws = await websockets.connect(self.url, max_size=None)
            self._authorized_accounts.clear()
            self._reader_task = asyncio.create_task(self._reader())
            self._heartbeat_task = asyncio.create_task(self._heartbeat())
            await self._send_and_wait(APPLICATION_AUTH_REQ, {
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
            })

    async def close(self):
        async with self._lock:
            await self._close_transport()

    async def _close_transport(self):
        for task in (self._heartbeat_task, self._reader_task):
            if task is not None:
                task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._reader_task = None
        self._heartbeat_task = None
        self._fail_pending(ConnectionError("conexión con cTrader cerrada"))

    def _fail_pending(self, exc):
        for queue in self._pending.values():
            queue.put_nowait(exc)
        self._pending.clear()

    async def _reader(self):
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                msg_id = message.get("clientMsgId")
                queue = self._pending.get(msg_id)
                if queue is not None:
                    queue.put_nowait(message)
                elif message.get("payloadType") != HEARTBEAT_EVENT:
                    log.debug("mensaje no solicitado: %s", message)
        except Exception as exc:
            log.warning("lector de cTrader terminado: %s", exc)
        finally:
            self._fail_pending(ConnectionError("conexión con cTrader cerrada"))

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._ws.send(json.dumps({"payloadType": HEARTBEAT_EVENT, "payload": {}}))
            except Exception:
                return

    async def _send_and_wait(self, payload_type, payload, until=None):
        msg_id = f"cm{next(self._ids)}"
        queue = asyncio.Queue()
        self._pending[msg_id] = queue
        try:
            await self._ws.send(json.dumps({
                "clientMsgId": msg_id,
                "payloadType": payload_type,
                "payload": payload,
            }))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout
            last = None
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    if last is not None:
                        return last
                    raise TimeoutError(f"sin respuesta de cTrader para payloadType {payload_type}")
                try:
                    message = await asyncio.wait_for(queue.get(), remaining)
                except asyncio.TimeoutError:
                    continue
                if isinstance(message, Exception):
                    raise message
                body = message.get("payload", {})
                if message.get("payloadType") in ERROR_TYPES:
                    raise CTraderError(body.get("errorCode"), body.get("description", ""))
                if until is None or until(message):
                    return body
                last = body
        finally:
            self._pending.pop(msg_id, None)

    async def request(self, payload_type, payload, until=None):
        if not self.connected:
            await self.connect()
        return await self._send_and_wait(payload_type, payload, until)

    async def ensure_account(self, account_id):
        account_id = int(account_id)
        if not self.connected:
            await self.connect()
        async with self._account_lock:
            if account_id not in self._authorized_accounts:
                await self._send_and_wait(ACCOUNT_AUTH_REQ, {
                    "ctidTraderAccountId": account_id,
                    "accessToken": self.access_token,
                })
                self._authorized_accounts.add(account_id)
        return account_id

    async def account_request(self, account_id, payload_type, payload=None, until=None):
        account_id = await self.ensure_account(account_id)
        body = {"ctidTraderAccountId": account_id}
        body.update(payload or {})
        return await self._send_and_wait(payload_type, body, until)
