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
"""

from __future__ import annotations

import json
from pathlib import Path

DESCONHECIDA = "desconhecida"


def integration_version() -> str:
    """Versao da integracao instalada.

    Sem cache: e um arquivo de ~300 bytes, lido no maximo a cada reconexao do
    tunel (ou a cada login). Guardar estado aqui so criaria a chance de ele
    ficar velho depois de uma atualizacao.

    Se a leitura falhar, devolve `desconhecida` em vez de inventar um numero —
    um valor inventado foi exatamente o que causou o problema original.
    """
    try:
        manifesto = Path(__file__).with_name("manifest.json")
        with manifesto.open(encoding="utf-8") as arquivo:
            return str(json.load(arquivo).get("version") or DESCONHECIDA)
    except (OSError, ValueError, AttributeError):
        return DESCONHECIDA
