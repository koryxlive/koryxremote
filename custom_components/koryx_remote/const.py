"""Constantes da integração Koryx Remote."""

DOMAIN = "koryx_remote"
DEFAULT_API_URL = "https://koryxremote.com"

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

# So luzes por enquanto. Cada dominio novo exige um mapeamento de capacidades
# proprio no Discovery da Alexa; `switch` e `cover` entram quando houver uso.
EXPOSABLE_DOMAINS = ("light",)
