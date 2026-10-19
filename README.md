# Koryx Remote — integração do Home Assistant

Acesse o seu Home Assistant de qualquer lugar, sem abrir portas no roteador.

Esta é a integração que o Home Assistant baixa. Ela abre uma conexão de saída
para o Koryx Remote e devolve a interface original do Home Assistant em
`https://{sua-casa}.koryx.one`.

> Migração de domínio pendente: `koryx.one` e `koryxremote.com` já estão registrados, mas a publicação de DNS/virada de tráfego ainda não foi concluída.

## Instalação

1. Crie a conta em [koryxremote.com](https://koryxremote.com).
2. No Home Assistant, instale esta integração (HACS ou cópia manual, abaixo).
3. Reinicie o Home Assistant.
4. Abra [Instalar no Home Assistant](https://my.home-assistant.io/redirect/config_flow_start/?domain=koryx_remote)
   e entre com o e-mail e a senha da sua conta Koryx Remote.

No fim, o próprio Home Assistant mostra o endereço da sua casa e o guarda em
`external_url`.

## Em casa vs fora (app e browser)

O endereço `https://{sua-casa}.koryx.one` **sempre** passa pelo túnel do Koryx —
mesmo se você estiver no Wi‑Fi de casa. Câmeras e dashboards nesse host consomem
a cota da nuvem. Em casa o ideal é o Home Assistant pela rede local.

### App Companion (automático)

No app, configure as duas URLs e o Wi‑Fi de casa (o app escolhe pela SSID):

| Campo | Valor |
| --- | --- |
| URL externa | `https://{sua-casa}.koryx.one` |
| URL interna | `http://homeassistant.local:8123` (ou o IP do HA na LAN) |
| Rede Wi‑Fi de casa | o SSID da sua rede |

Assim o celular usa a LAN em casa e o Koryx quando está fora. É o mesmo modelo
do Home Assistant Cloud / Nabu Casa.

### Browser, tablet e PC (orientação)

No navegador **não** há troca automática. Para dashboard fixo em casa
(tablet na parede, PC), use o favorito local:

- `http://homeassistant.local:8123`, ou
- `http://{IP-do-HA}:8123`

Reserve `https://{sua-casa}.koryx.one` para quando estiver fora.

> Rewrite DNS (AdGuard / Pi-hole) no host `koryx.one` **não** resolve o caso
> do browser: o certificado HTTPS fica na VPS do Koryx, não no HA. Apontar o
> nome para o IP local quebra o HTTPS. Use a URL local no favorito.

### Pelo HACS

1. HACS → Integrações → os três pontos → **Repositório customizado**.
2. URL: `https://github.com/koryxlive/koryxremote`
3. Categoria: **Integration**.
4. Instale **Koryx Remote** e reinicie o Home Assistant.

### Manual (sem HACS)

Baixe [koryx_remote.zip](https://koryxremote.com/ha/koryx_remote.zip), extraia em
`/config` do Home Assistant (fica `custom_components/koryx_remote`) e reinicie.

## Como funciona

- A conexão é de **dentro para fora**: o Home Assistant disca para o Relay, que
  só existe para casas conectadas. Não há porta aberta nem redirecionamento.
- Quem acessa a casa de fora entra com o **usuário do Home Assistant**, não com
  a conta Koryx.
- Os bytes do HTTP e do WebSocket passam pelo túnel como estão. O Koryx não
  lê o que você faz no seu Home Assistant.
- A senha da conta Koryx é usada uma vez, no login. Ela não fica gravada.

## Requisitos

- Home Assistant 2024.1 ou mais novo.

## Este repositório

Aqui fica **apenas** a integração. O serviço (API, Relay, painel) vive em outro
repositório, e o conteúdo dele é espelhado a partir de lá — não abra mudanças
neste repositório esperando que elas durem, porque o próximo espelho sobrescreve.

## Licença

Uso pessoal. Todos os direitos reservados.
