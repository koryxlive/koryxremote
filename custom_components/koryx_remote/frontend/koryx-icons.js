/**
 * Registra o K da marca como icone de frontend do Home Assistant.
 *
 * Por que este arquivo existe
 * --------------------------
 * O HA guarda o icone de um painel (`frontend.Panel.sidebar_icon`) como uma
 * **string** MDI — nao ha campo para imagem/PNG. A sidebar desenha com
 * `<ha-icon .icon=${panel.icon}>`, e o `<ha-icon>` resolve, nesta ordem:
 *
 *   1. prefixo MDI (`mdi:`), via o set de icones;
 *   2. prefixo registrado em `window.customIcons`, via `getIcon(name)`;
 *   3. nada conhecido: cai em `<iron-icon>` (legado) e **nao tenta de novo**.
 *
 * O passo 2 e o mesmo caminho que o HACS usa para o proprio logo e e API
 * publica do frontend (`src/data/custom_icons.ts`). Registrar aqui mantem o
 * painel como web component direto (`embed_iframe=False`), com o `hass`
 * compartilhado — o resto do painel (`hass.callWS`, `hass.callApi`,
 * `hass.language`) segue funcionando sem mudanca.
 *
 * Race com a sidebar (icone some as vezes)
 * ----------------------------------------
 * `frontend.add_extra_js_url` injeta este modulo de forma **assincrona**. A
 * sidebar pode pintar o `<ha-icon icon="koryx_remote:k">` **antes** de este
 * arquivo rodar. Nesse caso o `ha-icon` nao acha o prefixo em `customIcons`,
 * seta `_legacy = true` e renderiza `<iron-icon>` (vazio). Depois que o
 * registro chega, o elemento **nao re-consulta** — so chama `_loadIcon` de
 * novo se a propriedade `icon` mudar. Por isso o K some em alguns reloads e
 * volta em outros: e timing, nao cache quebrado.
 *
 * Mitigacao: depois de registrar, percorre o DOM (incluindo shadow roots) e
 * forca os `ha-icon` do nosso prefixo a carregar de novo — limpando `_legacy`
 * (senao o render continua no iron-icon mesmo com `_path` preenchido) e
 * reatribuindo `icon`. Retries curtos cobrem a sidebar que monta um pouco
 * depois do modulo.
 *
 * O contrato do `path` — e o bug da 0.2.27
 * ----------------------------------------
 * `getIcon` devolve `{path, viewBox}` e o `<ha-icon>` repassa o `path` ao
 * `<ha-svg-icon>`. **O `ha-svg-icon` nao insere markup**: ele faz
 *
 *     <path class="primary-path" d=${this.path}></path>
 *
 * e o `secondaryPath`, se houver, num segundo `<path>`. Entao `path` tem que
 * ser **path data de SVG** (`M ... L ... Z`) — **nao** um fragmento com
 * `<defs>`/`<linearGradient>`/varios `<path>`, como este arquivo montava na
 * 0.2.27. Aquele fragmento ia inteiro para o atributo `d`, o navegador
 * descartava o valor como path invalido, e o item da sidebar saia **vazio**:
 * `<ha-icon>` com `_path` preenchido, `<ha-svg-icon>` com `<svg>` e nenhum
 * desenho. Nao ha erro no console. Por isso aqui so existe um `d` unico.
 *
 * Custo aceito: o `ha-svg-icon` preenche com `currentcolor` e nao ha como
 * manter o gradiente do SVG da marca por este caminho. O K entra em
 * `currentcolor`, igual ao HACS — e e o que faz o icone acompanhar o tema
 * claro/escuro e o estado selecionado da sidebar.
 *
 * Os segmentos vem de `brand/logo-k-transparent.svg` (fonte da marca). Nao
 * concatenar a mao o SVG: `packages/integration/sidebar-icon.test.ts` compara
 * este `d` com os subpaths do SVG e falha se divergirem.
 */

const PREFIX = "koryx_remote";
const ICON_PREFIX = PREFIX + ":";

// Um `d` unico com os tres subpaths do K (o tubo diagonal, a haste e o pe).
// Ordem igual ao SVG: se mudar, o teste de paths acusa.
const K_PATH =
  "M 337 59 L 214 59 L 6 268 L 4 335 L 64 335 Z " +
  "M 4 4 L 6 235 L 93 147 L 94 96 Z " +
  "M 158 273 L 217 335 L 338 336 L 221 214 Z";

// `viewBox` do SVG da marca, em unidades do arquivo original.
const VIEW_BOX = "0 0 342 343";

const customIconsWindow = window;
if (!customIconsWindow.customIcons) {
  customIconsWindow.customIcons = {};
}

customIconsWindow.customIcons[PREFIX] = {
  // `getIcon` e **async** por contrato (ver `CustomIconHelpers` no frontend).
  // O `<ha-icon>` passa a Promise para `getIcon` e espera com `await`.
  getIcon: async (name) => {
    // Nome fora do contrato: o `<ha-icon>` nao pediria, mas devolver o K em
    // vez de lancar evita um icone vazio sem log caso o nome mude.
    if (name !== "k") {
      // eslint-disable-next-line no-console
      console.warn(`koryx: icone '${PREFIX}:${name}' nao existe; usando o K`);
    }
    return { path: K_PATH, viewBox: VIEW_BOX };
  },
};

/**
 * Forca `<ha-icon>` do nosso prefixo a sair do modo legado e recarregar.
 *
 * Precisa limpar `_legacy`: o `_loadIcon` do HA, ao achar o prefixo em
 * `customIcons`, preenche `_path` mas **nao** zera `_legacy`. Sem isso o
 * render continua no `<iron-icon>` vazio mesmo com o path certo.
 */
function reviveHaIcon(el) {
  const icon = el.icon || el.getAttribute?.("icon");
  if (!icon || !String(icon).startsWith(ICON_PREFIX)) {
    return;
  }
  // Campo privado do Lit no frontend do HA; sem isto o revive nao pinta.
  el._legacy = false;
  el.icon = "";
  el.icon = icon;
}

function walkShadow(root, visit) {
  if (!root || !root.querySelectorAll) {
    return;
  }
  root.querySelectorAll("ha-icon").forEach(visit);
  root.querySelectorAll("*").forEach((node) => {
    if (node.shadowRoot) {
      walkShadow(node.shadowRoot, visit);
    }
  });
}

function refreshSidebarIcons() {
  // O teste Node executa este arquivo sem `document`.
  if (typeof document === "undefined") {
    return;
  }
  walkShadow(document, reviveHaIcon);
}

refreshSidebarIcons();
// Sidebar pode montar depois do modulo: retries curtos cobrem o race tipico.
[50, 200, 500, 1000, 2000].forEach((ms) => {
  setTimeout(refreshSidebarIcons, ms);
});
