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
 *   2. prefixo registrado em `window.customIcons`, via `getIcon(name)`, que
 *      devolve um `path` SVG + `viewBox`.
 *
 * O passo 2 e o mesmo caminho que o HACS usa para o proprio logo e e API
 * publica do frontend (`src/data/custom_icons.ts`). Registrar aqui, e nao
 * trocar para `config_panel_domain` + iframe, mantem o painel como web
 * component direto (`embed_iframe=False`), com o `hass` compartilhado — o
 * resto do painel (`hass.callWS`, `hass.callApi`, `hass.language`) segue
 * funcionando sem mudanca.
 *
 * O que este arquivo NAO faz
 * --------------------------
 * Nao desenha nada e nao depende do `.js` do painel: e um modulo a parte,
 * injetado cedo pelo componente `frontend`, porque a sidebar desenha o icone
 * antes de qualquer navegacao para `/koryx-remote`.
 *
 * `getIcon` e **async** por contrato, mas o `getIcon` do `<ha-icon>` le a
 * `path` de forma sincrona no caminho comum (`customIcon.getIcon(iconName)`
 * recebe a Promise e `_setCustomPath` espera com `await`). Devolver a Promise
 * resolvida evita depender de timing.
 *
 * Os paths vem de `brand/logo-k-transparent.svg` (fonte da marca). Nao
 * editar a mao: `packages/integration/brand-icon.test.ts` compara este arquivo
 * com o SVG e falha se divergirem.
 */

const PREFIX = "koryx_remote";
const ICON = "k";

// `viewBox` do SVG da marca, em unidades do arquivo original.
const VIEW_BOX = "0 0 342 343";

// Um gradiente por <path> do SVG original. Cada um precisa de `id` unico:
// gradientes com o mesmo id colidem quando varias instancias do icone estao
// no DOM (a sidebar e o painel podem renderizar o mesmo icone ao mesmo tempo).
const PATHS = [
  {
    d: "M 337 59 L 214 59 L 6 268 L 4 335 L 64 335 Z",
    stops: [
      { offset: "0%", color: "#18BCF2" },
      { offset: "55%", color: "#03A9F4" },
      { offset: "100%", color: "#009AC7" },
    ],
  },
  {
    d: "M 4 4 L 6 235 L 93 147 L 94 96 Z",
    stops: [
      { offset: "0%", color: "#18BCF2" },
      { offset: "55%", color: "#03A9F4" },
      { offset: "100%", color: "#009AC7" },
    ],
  },
  {
    d: "M 158 273 L 217 335 L 338 336 L 221 214 Z",
    stops: [
      { offset: "0%", color: "#18BCF2" },
      { offset: "55%", color: "#03A9F4" },
      { offset: "100%", color: "#009AC7" },
    ],
  },
];

/**
 * Monta o `<path>` SVG do icone com os gradientes da marca.
 *
 * O `ha-svg-icon` aplica `fill: currentcolor` no host e o `fill` do `<path>`
 * vence isso — os gradientes precisam ser declarados dentro do SVG, porque
 * `var()` e `currentColor` nao atravessam um `<path d>` isolado.
 */
function buildPath() {
  const defs = PATHS.map((_, i) => {
    const stops = PATHS[i].stops
      .map((s) => `<stop offset="${s.offset}" stop-color="${s.color}"/>`)
      .join("");
    return `<linearGradient id="${PREFIX}-g${i}" x1="0%" y1="0%" x2="100%" y2="100%">${stops}</linearGradient>`;
  }).join("");

  const paths = PATHS.map(
    (p, i) => `<path d="${p.d}" fill="url(#${PREFIX}-g${i})"/>`,
  ).join("");

  return `<defs>${defs}</defs>${paths}`;
}

const ICON_PATH = buildPath();

const customIconsWindow = window;
if (!customIconsWindow.customIcons) {
  customIconsWindow.customIcons = {};
}

customIconsWindow.customIcons[PREFIX] = {
  getIcon: async (name) => {
    // Nome fora do contrato: o `<ha-icon>` nao pediria, mas devolver o K em
    // vez de lancar evita um icone vazio sem log caso o nome mude.
    if (name !== ICON) {
      // eslint-disable-next-line no-console
      console.warn(`koryx: icone '${PREFIX}:${name}' nao existe; usando o K`);
    }
    return { path: ICON_PATH, viewBox: VIEW_BOX };
  },
};
