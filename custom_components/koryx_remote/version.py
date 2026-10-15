"""Versao da integracao, lida do `manifest.json` numa fonte so.

Antes, o `version` do handshake era uma string fixa `"0.1.0"` escrita a mao em
dois lugares (`client.py` e `config_flow.py`). O efeito foi caro e silencioso:
o banco `agents.version` registrava `0.1.0` em TODO handshake, inclusive
depois de o usuario atualizar a integracao — entao o diagnostico mentia, e
"esta na versao antiga" parecia a unica leitura possivel mesmo quando a versao
ja era outra.

Agora a fonte e o `manifest.json`, que e o mesmo arquivo que o HACS usa para
decidir se ha atualizacao. Ler de la garante que o que o Relay registra e
exatamente o que esta instalado.

A leitura acontece no `async_setup_entry` (event loop) e o HA reclama de I/O
sincrono ali:

    Detected blocking call to open with args
    (PosixPath('/config/custom_components/koryx_remote/manifest.json'),)
    inside the event loop by custom integration 'koryx_remote'

Nao e um `open` grande, mas bloquear o loop atrasa todo mundo que espera por
ele, entao a leitura vai para o executor com `hass.async_add_executor_job`.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

DESCONHECIDA = "desconhecida"


def _read_manifest_version() -> str:
    """Le a versao do `manifest.json` (roda no executor, nao no loop).

    Se a leitura falhar, devolve `desconhecida` em vez de inventar um numero —
    um valor inventado foi exatamente o que causou o problema original.
    """
    try:
        manifesto = Path(__file__).with_name("manifest.json")
        with manifesto.open(encoding="utf-8") as arquivo:
            return str(json.load(arquivo).get("version") or DESCONHECIDA)
    except (OSError, ValueError, AttributeError):
        return DESCONHECIDA


async def async_integration_version(hass: HomeAssistant) -> str:
    """Versao da integracao instalada, sem bloquear o event loop.

    Sem cache: e um arquivo de ~300 bytes, lido no maximo a cada reconexao do
    tunel (ou a cada login). Guardar estado aqui so criaria a chance de ele
    ficar velho depois de uma atualizacao.
    """
    return await hass.async_add_executor_job(_read_manifest_version)


def integration_version() -> str:
    """Versao da integracao instalada, para quem JA esta fora do loop.

    Mantida como atalho sincrono (o `panel.py`, por exemplo, roda isto no
    setup, que e async). Prefira `async_integration_version` em codigo async.
    """
    return _read_manifest_version()
