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
 *   3. nada conhecido: cai em `<iron-icon>` (legado).
 *
 * O passo 2 e o mesmo caminho que o HACS usa para o proprio logo e e API
 * publica do frontend (`src/data/custom_icons.ts`). Registrar aqui mantem o
 * painel como web component direto (`embed_iframe=False`), com o `hass`
 * compartilhado — o resto do painel (`hass.callWS`, `hass.callApi`,
 * `hass.language`) segue funcionando sem mudanca.
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
