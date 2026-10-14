"""Túnel de saída: o HA fala com o Relay e entrega os bytes no HTTP local."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import aiohttp

_LOGGER = logging.getLogger(__name__)

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_CREDENTIAL,
    CONF_ENDS_AT,
    CONF_EXPOSED_ENTITIES,
    CONF_PLAN,
    CONF_RELAY_URL,
)

# Nome do plano para mostrar no HA. A chave é o id cru que a API manda; o valor
# é o que a pessoa lê. Plano que não estiver aqui volta cru, em vez de virar
# "desconhecido" — melhor mostrar `pro` do que esconder o que o servidor disse.
PLAN_LABELS = {
    "trial": "Trial",
    "basic": "Básico",
}


class TrialEnded(Exception):
    """O Relay recusou porque o trial acabou."""


def _in_cancellation() -> bool:
    """Estamos dentro de um `finally` que roda por cancelamento?

    Durante o cancelamento, `await` em I/O é arriscado: o loop pode não
    resolver o await e o desligamento fica preso. O sinal mais direto é o
    próprio state da task corrente — `cancelling() > 0` significa que o
    `CancelledError` foi levantado e ainda estamos processando o `finally`.
    """
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


class KoryxLink:
    """Uma conexão de saída e um status para o sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.connected = False
        # Vem do `/agents/link` e do `AUTH_OK`. O sensor de vencimento lê daqui.
        self.plan = str(entry.data.get(CONF_PLAN) or "trial")
        self.ends_at = _parse_datetime(entry.data.get(CONF_ENDS_AT))
        self._stop = asyncio.Event()
        self._listeners: list[Callable[[], None]] = []
        self._writers: dict[str, asyncio.StreamWriter] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    def update_entitlement(self, plan: Any, ends_at: Any) -> None:
        """Atualiza plano e fim do acesso, avisando só quando algo muda."""
        changed = False
        if isinstance(plan, str) and plan and plan != self.plan:
            self.plan = plan
            changed = True
        parsed = _parse_datetime(ends_at)
        if parsed != self.ends_at:
            self.ends_at = parsed
            changed = True
        if changed:
            self._notify()

    @property
    def plan_label(self) -> str:
        """Nome do plano para mostrar. Desconhecido volta cru, não inventado."""
        return PLAN_LABELS.get(self.plan, self.plan)

    @property
    def expiry(self) -> datetime | None:
        """Quando o acesso termina — trial, mês pago, ano pago.

        Sem exceção por plano: quem tem data mostra a data. A regra de esconder
        a data do plano pago saiu daqui junto com a coluna `trial_ends_at`; o
        servidor agora manda a renovação do plano pago no mesmo campo, e o
        sensor só desenha o que recebeu.
        """
        return self.ends_at

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
                    # Se o `finally` está rodando por causa de um cancelamento
                    # (shutdown/unload), não podemos dar `await` em rede: o HA
                    # já está finalizando e o await seguraria o desligamento. O
                    # `writer.close()` sozinho já libera o socket.
                    if _in_cancellation():
                        self._abort_streams()
                    else:
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
            # Handshake: plano e vencimento vêm junto para o sensor não ficar
            # preso ao que foi gravado no login.
            self.update_entitlement(frame.get("plan"), frame.get("endsAt"))
            # A lista de entidades expostas vai logo depois do AUTH_OK: é o que
            # alimenta o Discovery da Alexa, e ela muda sem reconectar.
            await self._send_exposed_entities()
            return True
        if kind == "PONG":
            # A cada PING (~15 s) o Relay reenvia plano/endsAt. Sem isso, uma
            # mudança no /kxpanel só apareceria no HA depois de reconectar.
            self.update_entitlement(frame.get("plan"), frame.get("endsAt"))
            return authed
        error = frame.get("error")
        if kind == "ERROR" and isinstance(error, dict) and error.get("code") == "PLAN_EXPIRED":
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
        # Directive da Alexa: processa e devolve a resposta pelo mesmo túnel.
        # Não tem `streamId`, então precisa vir antes da checagem de stream.
        if payload.get("kind") == "directive":
            await self._handle_directive(payload)
            return
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

    async def _handle_directive(self, payload: dict[str, Any]) -> None:
        """Processa um directive da Alexa e devolve a resposta.

        A resposta carrega o `correlationId` que a API mandou: é o que liga a
        resposta à requisição HTTP que está esperando do outro lado. Sem ele a
        API não teria como casar as duas pontas, já que o túnel é multiplexado.

        Um erro aqui é respondido como erro da Alexa, nunca engolido: a API
        está esperando um corpo e um timeout parece "casa fora do ar", que é
        um diagnóstico pior do que "não consegui".
        """
        correlation_id = payload.get("correlationId")
        request = payload.get("directive")
        if not isinstance(correlation_id, str) or not isinstance(request, dict):
            return
        try:
            from .alexa import async_handle_directive

            response = await async_handle_directive(self.hass, self.entry, request)
        except Exception:
            _LOGGER.exception("Falha ao processar directive da Alexa")
            response = None
        await self._send_payload(
            {
                "kind": "directive_response",
                "correlationId": correlation_id,
                "response": response,
            }
        )

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

    async def notify_entities_changed(self) -> None:
        """
        Reenvia a lista de entidades expostas, se houver conexão.

        Chamado quando o usuário muda a escolha na tela de Opções. Sem isto a
        nova seleção só valeria na próxima reconexão do túnel — o usuário
        marcaria uma luz e ela não apareceria na Alexa, o que parece defeito.
        Se o túnel estiver caído, o `AUTH_OK` da reconexão já reenvia a lista,
        então não há o que recuperar aqui.
        """
        await self._send_exposed_entities()

    async def _send_exposed_entities(self) -> None:
        """Avisa a API que a seleção de entidades mudou.

        A lista em si não viaja: com o directive cru indo para o HA, quem
        responde o Discovery é o `alexa_smart_home` do core, lendo a seleção
        local. O que a API precisa saber é só que existe algo para anunciar —
        para ela invalidar cache, se um dia tiver.

        O `entityId` de cada escolhida vai junto porque é barato e ajuda o log
        da API a mostrar o que a casa declarou, sem ser fonte de verdade.
        """
        entidades = [
            entity_id
            for entity_id in (self.entry.options.get(CONF_EXPOSED_ENTITIES) or [])
            if isinstance(entity_id, str) and self.hass.states.get(entity_id) is not None
        ]
        await self._send_payload({"kind": "entities", "entities": entidades})

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

    def _abort_streams(self) -> None:
        """Fecha os writers sem `await`.

        Usado no caminho de cancelamento: `writer.close()` libera o socket na
        hora e não suspende a task, então o fechamento não segura o shutdown.
        Não precisa de `wait_closed()` aqui — o processo está terminando e não
        há mais ninguém esperando o drain.
        """
        for stream_id in list(self._writers):
            writer = self._writers.pop(stream_id, None)
            if writer is not None:
                writer.close()

    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        self._notify()

    def _notify(self) -> None:
        for update in list(self._listeners):
            update()


def _parse_datetime(value: Any) -> datetime | None:
    """Aceita o ISO que a API manda e devolve consciente de fuso (UTC)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
