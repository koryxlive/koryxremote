"""Constantes da integração Koryx Remote."""

DOMAIN = "koryx_remote"
DEFAULT_API_URL = "https://koryxremote.com"

# Manifest do repo público do HACS — mesma fonte que o `sync-integration.sh`
# publica. A integração consulta isto antes do `/ha/version` da API.
GITHUB_MANIFEST_URL = (
    "https://raw.githubusercontent.com/koryxlive/koryxremote/main/"
    "custom_components/koryx_remote/manifest.json"
)

# Intervalo do check de versão (sensor + update + push). 12 h basta: release
# não é contínua, e evita bater no GitHub/API a cada minuto.
UPDATE_CHECK_HOURS = 12

# Última versão para a qual já criamos a persistent_notification. Em
# `entry.data` para sobreviver a restart sem repetir o push.
CONF_UPDATE_NOTIFIED = "update_notified_version"


# Fabricante do dispositivo no device registry. Um nome proprio, e nao o de uma
# marca que ja exista no catalogo de marcas do HA: o dispositivo herda o icone
# do fabricante, e usar "Home Assistant" faria o dispositivo do usuario exibir
# o logo do HA. Sem entrada no catalogo, o HA cai no icone da integracao, que
# desde a 2026.3 e o local (`brand/icon.png`).
MANUFACTURER = "Koryx"

CONF_API_URL = "api_url"
CONF_EMAIL = "email"
CONF_CREDENTIAL = "credential"
CONF_RELAY_URL = "relay_url"
CONF_SLUG = "slug"
CONF_URL = "url"
CONF_PLAN = "plan"
CONF_ENDS_AT = "ends_at"

# Entidades que o HA declara para a Alexa. Guardado nas options da entry, e nao
# em `data`: o que o usuario escolhe depois de configurar pertence a `options`,
# que o HA trata como mutavel sem reconfigurar a integracao.
CONF_EXPOSED_ENTITIES = "exposed_entities"

# Id do usuário de sistema que assina as ações vindas da Alexa. Fica em
# `options` para a integração reaproveitar o mesmo usuário entre reloads, em
# vez de criar um novo a cada vez. Ver `alexa._async_system_user_id`.
CONF_ALEXA_USER_ID = "alexa_user_id"

# Report State proativo: o HA avisa a Alexa quando uma luz muda por fora (na
# parede, por automação). Opt-in — gera tráfego a cada mudança reportável. Ver
# `docs/report-state.md`.
CONF_REPORT_STATE = "report_state"

# Dominios que a integracao deixa escolher na tela de Opcoes. A lista e a unica
# fonte de verdade do escopo: o `EntitySelector` do `config_flow` filtra por
# ela, o painel da sidebar recebe a mesma lista em `config.domains`, e o
# `should_expose` aceita o que o usuario marcou.
#
# Nao ha mapeamento de capacidades aqui — quem traduz `cover` em `SetPosition`,
# `climate` em `SetTargetTemperature`, `fan` em percentual ou `vacuum` em
# start/return e o `ENTITY_ADAPTERS` do core, por dominio. Ampliar o escopo e
# acrescentar um nome nesta tupla, nao mexer na logica. Cada dominio novo so
# precisa entrar aqui e ter rotulo/icone no painel (`DOMAIN_LABELS`).
#
# `lock` entra: o core ja traduz Lock/Unlock; o PIN de 4 digitos e so no app
# da Alexa (nao chega ao HA). `alarm_control_panel` continua fora — o disarm
# pode carregar codigo no directive e e outro risco. Ver `docs/alexa.md`.
# `sensor`/`binary_sensor`/`number` tambem ficam: so reportam, nunca executam,
# e so poluem o app.
EXPOSABLE_DOMAINS = (
    "light",
    "cover",
    "climate",
    "switch",
    "fan",
    "vacuum",
    "lock",
)

# Prefixo do icone da marca na sidebar. O HA nao aceita imagem em `sidebar_icon`
# de `panel_custom` (o `frontend.Panel` guarda so uma string MDI e a sidebar
# resolve via `<ha-icon>`), entao a marca entra pelo registro `window.customIcons`
# que o proprio `<ha-icon>` consulta para prefixos fora do MDI. O prefixo precisa
# ser unico para nao colidir com conjunto de icones de terceiros; o nome segue
# `koryx_remote` e nao `koryx`, que o Live pode querer usar.
CUSTOM_ICON_PREFIX = "koryx_remote"

# Categoria da Alexa por `device_class` de `cover`. O core ja faz esse mapa em
# `CoverCapabilities.default_display_categories`, mas **so quando a entidade
# declara `device_class`**: sem ele, cai em `OTHER` e o app mostra "Outro".
#
# A maioria das cortinas/persianas do mundo real vem de MQTT/Tuya/HomeKit que
# nao publicam `device_class` — e nao da para pedir ao usuario que edite o HA
# de cada dispositivo dele. Entao inferimos aqui: este mapa e a fonte de
# verdade da categoria quando o core nao tem com o que decidir. Onde o core
# decide (device_class presente), nao interferimos — ver `alexa.entity_config`.
#
# Valores sao `DisplayCategory` do core (`INTERIOR_BLIND`, `EXTERIOR_BLIND`,
# `DOOR`, `GARAGE_DOOR`). Um device_class fora daqui (ou ausente) vira
# `COVER_DEFAULT_DISPLAY_CATEGORY` — hoje "persiana interna", que e o rotulo
# que a Alexa usa para cortina/veneziana/persiana e o caso mais comum.
COVER_DISPLAY_CATEGORIES: dict[str, str] = {
    "blind": "INTERIOR_BLIND",
    "shade": "INTERIOR_BLIND",
    "curtain": "INTERIOR_BLIND",
    "window": "EXTERIOR_BLIND",
    "awning": "EXTERIOR_BLIND",
    "shutter": "EXTERIOR_BLIND",
    "door": "DOOR",
    "garage": "GARAGE_DOOR",
    "gate": "GARAGE_DOOR",
}

COVER_DEFAULT_DISPLAY_CATEGORY = "INTERIOR_BLIND"
