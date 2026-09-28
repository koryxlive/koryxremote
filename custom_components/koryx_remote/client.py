"""Túnel de saída: o HA fala com o Relay e entrega os bytes no HTTP local."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import CONF_CREDENTIAL, CONF_RELAY_URL


class TrialEnded(Exception):
    """O Relay recusou porque o trial acabou."""


class KoryxLink:
    """Uma conexão de saída e um status para o sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.connected = False
        self._stop = asyncio.Event()
        self._listeners: list[Callable[[], None]] = []
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)

        def remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return remove

    async def run(self) -> None:
        delay = 1
        while not self._stop.is_set():
            try:
                await self._connect_once()
                delay = 1
            except asyncio.CancelledError:
                raise
            except TrialEnded:
                self._set_connected(False)
                delay = 300
            except Exception:
                self._set_connected(False)
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), delay)
            except TimeoutError:
                delay = min(delay * 2, 30)

    async def async_stop(self) -> None:
        self._stop.set()
        await self._shutdown()

    async def _connect_once(self) -> None:
        credential = str(self.entry.data[CONF_CREDENTIAL])
        relay_url = str(self.entry.data[CONF_RELAY_URL])
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(relay_url, heartbeat=None) as ws:
                self._ws = ws
                await self._send_frame("HELLO", None)
                await self._send_frame(
                    "AUTH",
                    json.dumps({"credential": credential, "version": "0.1.0"}),
                )
                authed = False
                ping = asyncio.create_task(self._ping(ws))
                try:
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            if message.type in (
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break
                            continue
                        authed = await self._on_message(message.data, authed)
                finally:
                    ping.cancel()
                    self._ws = None
                    await self._shutdown_streams()
                    self._set_connected(False)
                    if ws.close_code == 4403:
                        raise TrialEnded

    async def _ping(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while True:
            await asyncio.sleep(15)
            if ws.closed:
                return
            await self._send_frame("PING", None)

    async def _on_message(self, raw: str, authed: bool) -> bool:
        try:
            frame: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            return authed
        kind = frame.get("type")
        if kind == "AUTH_OK":
            self._set_connected(True)
            return True
        error = frame.get("error")
        if kind == "ERROR" and isinstance(error, dict) and error.get("code") == "TRIAL_EXPIRED":
            raise TrialEnded
        if kind != "DATA" or not authed:
            return authed
        data = frame.get("data")
        if not isinstance(data, str):
            return authed
        try:
            payload: dict[str, Any] = json.loads(data)
        except json.JSONDecodeError:
            return authed
        await self._on_payload(payload)
        return authed

    async def _on_payload(self, payload: dict[str, Any]) -> None:
        stream_id = payload.get("streamId")
        if not isinstance(stream_id, str):
            return
        kind = payload.get("kind")
        if kind == "stream_open":
            await self._open_stream(stream_id)
            return
        if kind == "stream_data" and isinstance(payload.get("b64"), str):
            writer = self._writers.get(stream_id)
            if writer is None:
                return
            writer.write(base64.b64decode(payload["b64"]))
            await writer.drain()
            return
        if kind == "stream_close":
            await self._close_stream(stream_id)

    async def _open_stream(self, stream_id: str) -> None:
        http = getattr(self.hass, "http", None)
        port = int(getattr(http, "server_port", None) or 8123)
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await self._send_payload({"kind": "stream_close", "streamId": stream_id})
            return
        self._writers[stream_id] = writer
        task = asyncio.create_task(self._pump(stream_id, _reader))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _pump(self, stream_id: str, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                chunk = await reader.read(16 * 1024)
                if not chunk:
                    break
                await self._send_payload(
                    {"kind": "stream_data", "streamId": stream_id, "b64": base64.b64encode(chunk).decode("ascii")}
                )
        finally:
            await self._send_payload({"kind": "stream_close", "streamId": stream_id})
            await self._close_stream(stream_id)

    async def _close_stream(self, stream_id: str) -> None:
        writer = self._writers.pop(stream_id, None)
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            return

    async def _send_payload(self, payload: dict[str, Any]) -> None:
        await self._send_frame("DATA", json.dumps(payload))

    async def _send_frame(self, kind: str, data: str | None) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            return
        frame: dict[str, Any] = {"v": 1, "type": kind, "id": str(uuid4())}
        if data is not None:
            frame["data"] = data
        await ws.send_str(json.dumps(frame))

    async def _shutdown(self) -> None:
        await self._shutdown_streams()
        ws = self._ws
        self._ws = None
        if ws is not None and not ws.closed:
            await ws.close()

    async def _shutdown_streams(self) -> None:
        for stream_id in list(self._writers):
            await self._close_stream(stream_id)

    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        for update in list(self._listeners):
            update()
