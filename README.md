# Koryx Remote — integração do Home Assistant

Acesse o seu Home Assistant de qualquer lugar, sem abrir portas no roteador.

Esta é a integração que o Home Assistant baixa. Ela abre uma conexão de saída
para o Koryx Remote e devolve a interface original do Home Assistant em
`https://{sua-casa}.koryx.one`.

> Migração de domínio pendente: `koryx.one` e `koryxremote.com` já estão registrados, mas a publicação de DNS/virada de tráfego ainda não foi concluída.

## Instalação

1. Crie a conta em [koryxremote.com](https://koryxremote.com). O hub [koryx.com.br](https://koryx.com.br) apresenta as plataformas (Live e Remote) e aponta para elas.
2. No Home Assistant, instale esta integração (HACS ou cópia manual, abaixo).
3. Reinicie o Home Assistant.
4. Abra [Instalar no Home Assistant](https://my.home-assistant.io/redirect/config_flow_start/?domain=koryx_remote)
   e entre com o e-mail e a senha da sua conta Koryx Remote.

No fim, o próprio Home Assistant mostra o endereço da sua casa e o guarda em
`external_url`.

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
