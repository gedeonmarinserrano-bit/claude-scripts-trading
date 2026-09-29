import asyncio
import json

import pytest
import websockets

from ctrader_mcp import client as api
from ctrader_mcp.client import CTraderClient, CTraderError


async def fake_ctrader(ws):
    async for raw in ws:
        msg = json.loads(raw)
        kind, body, msg_id = msg["payloadType"], msg.get("payload", {}), msg.get("clientMsgId")

        async def reply(payload_type, payload):
            await ws.send(json.dumps({"clientMsgId": msg_id, "payloadType": payload_type, "payload": payload}))

        if kind == api.HEARTBEAT_EVENT:
            continue
        if kind == api.APPLICATION_AUTH_REQ:
            await reply(2101, {})
        elif kind == api.ACCOUNT_AUTH_REQ:
            if body["accessToken"] != "token":
                await reply(api.OA_ERROR_RES, {"errorCode": "CH_ACCESS_TOKEN_INVALID", "description": "bad"})
            else:
                await reply(2103, {"ctidTraderAccountId": body["ctidTraderAccountId"]})
        elif kind == api.TRADER_REQ:
            await reply(2122, {"trader": {"balance": 123456, "moneyDigits": 2}})
        elif kind == api.NEW_ORDER_REQ:
            await reply(api.EXECUTION_EVENT, {"executionType": "ORDER_ACCEPTED"})
            await reply(api.EXECUTION_EVENT, {"executionType": "ORDER_FILLED", "position": {"positionId": 9}})


def run_with_server(coro_factory):
    async def main():
        async with websockets.serve(fake_ctrader, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            return await coro_factory(f"ws://127.0.0.1:{port}")
    return asyncio.run(main())


def test_account_request_authenticates_and_returns_payload():
    async def scenario(url):
        c = CTraderClient("id", "secret", "token", host=url, timeout=2)
        try:
            return await c.account_request(1, api.TRADER_REQ)
        finally:
            await c.close()

    assert run_with_server(scenario) == {"trader": {"balance": 123456, "moneyDigits": 2}}


def test_until_waits_for_matching_event():
    async def scenario(url):
        c = CTraderClient("id", "secret", "token", host=url, timeout=2)
        try:
            return await c.account_request(
                1, api.NEW_ORDER_REQ, {},
                lambda m: m["payload"].get("executionType") == "ORDER_FILLED")
        finally:
            await c.close()

    assert run_with_server(scenario)["position"]["positionId"] == 9


def test_error_response_raises():
    async def scenario(url):
        c = CTraderClient("id", "secret", "wrong", host=url, timeout=2)
        try:
            await c.account_request(1, api.TRADER_REQ)
        finally:
            await c.close()

    with pytest.raises(CTraderError, match="CH_ACCESS_TOKEN_INVALID"):
        run_with_server(scenario)
