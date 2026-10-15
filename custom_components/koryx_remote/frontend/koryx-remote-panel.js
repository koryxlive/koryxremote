import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

/**
 * Koryx Remote — escolha dos dispositivos que a Alexa enxerga.
 *
 * Por que este painel existe
 * --------------------------
 * O formulário de Opções da integração usa o `EntitySelector` do HA, que dá
 * busca e seleção múltipla — mas **não** dá filtro por domínio em forma de
 * abas. O `filter` do HA só *restringe* a lista em silêncio; não desenha chip
 * clicável. Numa casa com 141 `light` + 11 `cover` + 7 `climate`, procurar na
 * lista misturada é pior que poder dizer "só cortinas" antes de digitar.
 *
 * O que este painel acrescenta, e só isso:
 *   - busca por nome/entity_id;
 *   - filtro por domínio (Luz / Cortina / Clima);
 *   - seleção que **sobrevive à troca de filtro** — marcar uma luz, filtrar
 *     só cortinas, marcar mais, e aplicar a união de uma vez.
 *
 * A fonte de verdade continua sendo `entry.options["exposed_entities"]`: o
 * painel lê e grava exatamente ali, pelo mesmo websocket que o formulário
 * nativo usa. Não há uma segunda cópia da seleção.
 */

const DOMAIN_LABELS = {
  light: { pt: "Luzes", en: "Lights", icon: "mdi:lightbulb" },
  cover: { pt: "Cortinas", en: "Covers", icon: "mdi:window-shutter" },
  climate: { pt: "Clima", en: "Climate", icon: "mdi:thermostat" },
};

const STRINGS = {
  pt: {
    title: "Dispositivos para a Alexa",
    subtitle: "Só os marcados aqui aparecem no app da Alexa.",
    search: "Buscar por nome…",
    all: "Todos",
    selected: "selecionados",
    save: "Salvar",
    saving: "Salvando…",
    saved: "Seleção salva.",
    saveFailed: "Não foi possível salvar. Tente de novo.",
    loadFailed: "Não foi possível carregar os dispositivos.",
    empty: "Nenhum dispositivo encontrado.",
    emptyFilter: "Nada com esse nome neste filtro.",
    clear: "Limpar",
    selectAll: "Marcar todos os visíveis",
    unselectAll: "Desmarcar todos",
  },
  en: {
    title: "Devices for Alexa",
    subtitle: "Only the ones selected here appear in the Alexa app.",
    search: "Search by name…",
    all: "All",
    selected: "selected",
    save: "Save",
    saving: "Saving…",
    saved: "Selection saved.",
    saveFailed: "Could not save. Try again.",
    loadFailed: "Could not load devices.",
    empty: "No devices found.",
    emptyFilter: "Nothing matches that name in this filter.",
    clear: "Clear",
    selectAll: "Select all visible",
    unselectAll: "Unselect all",
  },
};

class KoryxRemotePanel extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      _entries: { type: Array },
      _selected: { type: Object },
      _domain: { type: String },
      _query: { type: String },
      _loading: { type: Boolean },
      _saving: { type: Boolean },
      _error: { type: String },
      _savedFlash: { type: Boolean },
    };
  }

  constructor() {
    super();
    /** @type {Set<string>} entidades já escolhidas (fonte da verdade local) */
    this._selected = new Set();
    /** @type {Array<{entity_id: string, name: string, domain: string}>} */
    this._entries = [];
    this._domain = "all";
    this._query = "";
    this._loading = true;
    this._saving = false;
    this._error = "";
    this._savedFlash = false;
    this._loadedOnce = false;
    /**
     * Flow de options aberto no `_load`, esperando o `user_input`. Reaproveitar
     * o mesmo flow evita abrir um segundo só para salvar — e, como abrir não
     * grava nada, ler o default dele é o jeito suportado de conhecer a
     * seleção atual (o `options` não vem por websocket).
     * @type {string|null}
     */
    this._pendingFlowId = null;
  }

  updated(changed) {
    // O `hass` chega depois de o elemento montar; só então há websocket.
    if (changed.has("hass") && this.hass && !this._loadedOnce) {
      this._loadedOnce = true;
      this._load();
    }
  }

  get _lang() {
    // `pt-BR` e `pt` compartilham o dicionário; o resto cai no inglês.
    const l = (this.hass && this.hass.language) || "en";
    return l.toLowerCase().startsWith("pt") ? "pt" : "en";
  }

  get _t() {
    return STRINGS[this._lang];
  }

  /**
   * Cria o options flow da entry e devolve a resposta crua.
   *
   * O options flow é **REST** (`/api/config/config_entries/options/flow`),
   * não websocket — o `options` nem sequer vem no `config_entries/get_single`
   * (o `as_json_fragment` do core não o inclui). Este é o mesmo caminho que o
   * formulário de Opções nativo usa, então é o único jeito suportado de ler e
   * gravar a seleção sem escrever direto no storage.
   */
  async _openFlow(entryId) {
    return this.hass.callApi("POST", "config/config_entries/options/flow", {
      handler: entryId,
    });
  }

  /** Submete o flow já aberto com os dados; devolve a resposta.
   *
   * As chaves vao **direto no corpo**, nao dentro de `user_input`. Essa e a
   * forma que o HA 2026.10 aceita; envolver em `user_input` devolve
   * `400 {"errors":{"base":["not a valid option at 'user_input'"]}}` e nada
   * e gravado. Verificado contra a API real do HA 2026.10.1: o mesmo corpo
   * sem o envelope responde `{"type":"create_entry"}` e grava as options.
   */
  async _submitFlow(flowId, userInput) {
    return this.hass.callApi(
      "POST",
      `config/config_entries/options/flow/${flowId}`,
      userInput,
    );
  }

  /** Acha a entry `koryx_remote` (a primeira; a conta é uma só). */
  async _myEntryId() {
    const entries = await this.hass.callWS({ type: "config_entries/get" });
    const mine = entries.filter((e) => e.domain === "koryx_remote");
    return mine.length ? mine[0].entry_id : null;
  }

  async _load() {
    this._loading = true;
    this._error = "";
    try {
      const entryId = await this._myEntryId();
      if (!entryId) {
        this._entries = [];
        return;
      }

      // 1) Abrir o flow só para ler o valor atual: o schema do step `init`
      // traz `exposed_entities` com o default já preenchido — é a seleção
      // salva. (Abrir um flow não grava nada; ele fica pendente e some.)
      const flow = await this._openFlow(entryId);
      const chosen = new Set(this._readDefault(flow, "exposed_entities"));
      this._pendingFlowId = flow.flow_id;
      this._selected = chosen;

      // 2) O catálogo de entidades elegíveis, com nome amigável.
      const list = await this._fetchExposable();
      // Preserva o que já estava marcado mesmo se a listagem mudou desde
      // então (uma entidade removida do HA não deve sumir do painel sem
      // aviso — mostramos ela com o próprio id).
      const byId = new Map(list.map((x) => [x.entity_id, x]));
      for (const id of chosen) {
        if (!byId.has(id)) {
          byId.set(id, { entity_id: id, name: id, domain: id.split(".")[0] });
        }
      }
      this._entries = [...byId.values()].sort((a, b) =>
        a.name.localeCompare(b.name, this._lang, { sensitivity: "base" }),
      );
    } catch (err) {
      this._error = this._t.loadFailed;
      // eslint-disable-next-line no-console
      console.error("koryx panel: falha ao carregar", err);
    } finally {
      this._loading = false;
    }
  }

  /**
   * Extrai o default de um campo do `data_schema` que o flow devolveu.
   *
   * O HA serializa o schema de duas formas, dependendo do caminho:
   *
   *   A) forma "seletor", que e a que a API HTTP devolve hoje:
   *      `[{"name": "exposed_entities", "default": [...], "selector": {...}}, ...]`
   *
   *   B) forma "voluptuous", com a chave sendo o proprio nome do campo:
   *      `[{"exposed_entities": {"default": [...], "selector": {...}}}, ...]`
   *
   * A versao anterior so entendia a (B). Contra a API real (HA 2026.10.1) o
   * schema vem na forma (A), entao a busca nunca casava e o painel abria
   * **sem nada marcado** — mesmo com a selecao gravada e funcionando na Alexa.
   * Aceitar as duas evita depender de qual caminho serializou.
   */
  _readDefault(flow, key) {
    const schema = flow && flow.data_schema;
    if (!Array.isArray(schema)) return [];
    for (const item of schema) {
      if (!item || typeof item !== "object") continue;
      // Forma (A): o nome do campo fica em `name`.
      if (item.name === key && "default" in item) return item.default || [];
      // Forma (B): a chave do objeto e o nome do campo.
      const vol = item.schema || item;
      for (const [k, v] of Object.entries(vol)) {
        if (k !== key) continue;
        if (v && typeof v === "object" && "default" in v) return v.default || [];
        return [];
      }
    }
    return [];
  }

  /**
   * Entidades elegíveis, com nome e domínio.
   *
   * Usa o registry (área 3 = entidade) via `config/entity_registry/list`, e
   * filtra pelos domínios que a integração expõe. O `friendly_name` do
   * registry é o que o usuário vê em todo o HA — é o nome certo para buscar.
   */
  async _fetchExposable() {
    const allowed = (this.panel && this.panel.config && this.panel.config.domains) || [
      "light",
      "cover",
      "climate",
    ];
    const registry = await this.hass.callWS({ type: "config/entity_registry/list" });
    return registry
      .filter((e) => allowed.includes(e.entity_id.split(".")[0]))
      .filter((e) => !e.hidden_by && !e.disabled_by)
      .map((e) => ({
        entity_id: e.entity_id,
        name: e.name || e.original_name || e.entity_id,
        domain: e.entity_id.split(".")[0],
      }));
  }

  get _visible() {
    const q = this._query.trim().toLowerCase();
    return this._entries.filter((e) => {
      if (this._domain !== "all" && e.domain !== this._domain) return false;
      if (!q) return true;
      return (
        e.name.toLowerCase().includes(q) || e.entity_id.toLowerCase().includes(q)
      );
    });
  }

  toggle(entityId) {
    const next = new Set(this._selected);
    if (next.has(entityId)) next.delete(entityId);
    else next.add(entityId);
    this._selected = next;
  }

  selectAllVisible() {
    const next = new Set(this._selected);
    for (const e of this._visible) next.add(e.entity_id);
    this._selected = next;
  }

  unselectAll() {
    this._selected = new Set();
  }

  async save() {
    if (this._saving) return;
    this._saving = true;
    this._error = "";
    try {
      // Reaproveita o flow aberto no load. Ele ainda está pendente no
      // backend esperando o `user_input`; submeter agora grava a seleção e
      // dispara o update listener da entry (que reenvia a lista à API e faz
      // a Alexa enxergar a mudança sem esperar reconexão).
      const flowId = this._pendingFlowId;
      if (!flowId) {
        // Sem flow (o load falhou ou já foi consumido): abre um novo.
        const entryId = await this._myEntryId();
        if (!entryId) throw new Error("sem entry koryx_remote");
        const flow = await this._openFlow(entryId);
        this._pendingFlowId = flow.flow_id;
        const again = await this._submitFlow(flow.flow_id, {
          exposed_entities: [...this._selected],
        });
        this._handlePostSave(again);
        return;
      }
      const result = await this._submitFlow(flowId, {
        exposed_entities: [...this._selected],
      });
      // O flow termina ao gravar: o id deixa de valer. Sem limpar, um segundo
      // "Salvar" mandaria um flow_id morto e tomaria 404.
      this._pendingFlowId = null;
      this._handlePostSave(result);
    } catch (err) {
      this._error = this._t.saveFailed;
      // eslint-disable-next-line no-console
      console.error("koryx panel: falha ao salvar", err);
    } finally {
      this._saving = false;
    }
  }

  /** Fecha o flow que sobrou (se houver) e mostra o "salvo". */
  _handlePostSave() {
    if (this._pendingFlowId) {
      // Após gravar, o flow pode ter avançado de step (o nosso não avança,
      // mas o contrato permite). Fecha para não deixar flow pendente.
      const stale = this._pendingFlowId;
      this._pendingFlowId = null;
      this.hass
        .callApi("DELETE", `config/config_entries/options/flow/${stale}`)
        .catch(() => {});
    }
    this._savedFlash = true;
    setTimeout(() => {
      this._savedFlash = false;
    }, 2500);
  }

  render() {
    const t = this._t;
    if (this._loading) {
      return html`<div class="wrap"><ha-circular-progress active></ha-circular-progress></div>`;
    }

    const doms = ["all", ...Object.keys(DOMAIN_LABELS)];
    const counts = {};
    for (const e of this._entries) {
      counts[e.domain] = (counts[e.domain] || 0) + 1;
    }

    return html`
      <div class="wrap">
        <header>
          <h1>${t.title}</h1>
          <p class="sub">${t.subtitle}</p>
        </header>

        <div class="bar">
          <ha-input
            class="search"
            .value=${this._query}
            .label=${t.search}
            .placeholder=${t.search}
            @input=${(e) => {
              this._query = e.target.value;
            }}
          ></ha-input>
          <div class="tabs">
            ${doms.map(
              (d) => html`
                <button
                  class="tab ${this._domain === d ? "on" : ""}"
                  @click=${() => {
                    this._domain = d;
                  }}
                >
                  ${d === "all" ? t.all : DOMAIN_LABELS[d][this._lang]}
                  ${d !== "all" && counts[d] ? html`<span class="n">${counts[d]}</span>` : ""}
                </button>
              `,
            )}
          </div>
        </div>

        <div class="meta">
          <span>${this._selected.size} ${t.selected}</span>
          <span class="actions">
            <button @click=${this.selectAllVisible}>${t.selectAll}</button>
            <button @click=${this.unselectAll}>${t.unselectAll}</button>
          </span>
        </div>

        ${this._error ? html`<div class="err">${this._error}</div>` : ""}

        <ul class="list">
          ${this._visible.length === 0
            ? html`<li class="none">${this._query ? t.emptyFilter : t.empty}</li>`
            : this._visible.map(
                (e) => html`
                  <li class="${this._selected.has(e.entity_id) ? "sel" : ""}">
                    <label>
                      <ha-checkbox
                        .checked=${this._selected.has(e.entity_id)}
                        @change=${() => this.toggle(e.entity_id)}
                      ></ha-checkbox>
                      <ha-icon
                        .icon=${DOMAIN_LABELS[e.domain] ? DOMAIN_LABELS[e.domain].icon : "mdi:shape"}
                      ></ha-icon>
                      <span class="nm">${e.name}</span>
                      <span class="id">${e.entity_id}</span>
                    </label>
                  </li>
                `,
            )}
        </ul>

        <footer>
          <ha-button @click=${this.save} .disabled=${this._saving}>
            ${this._saving ? t.saving : t.save}
          </ha-button>
          ${this._savedFlash ? html`<span class="ok">${t.saved}</span>` : ""}
        </footer>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        padding: 16px;
      }
      .wrap {
        max-width: 720px;
        margin: 0 auto;
      }
      h1 {
        font-size: 1.5rem;
        margin: 0;
      }
      .sub {
        color: var(--secondary-text-color);
        margin: 4px 0 16px;
      }
      .bar {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .search {
        width: 100%;
        /* Um custom element do HA nao registrado colapsa para altura 0. A
           altura minima faz o campo continuar visivel mesmo se o elemento
           mudar de nome numa proxima versao do HA. */
        min-height: 56px;
      }
      .tabs {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .tab {
        border: 1px solid var(--divider-color);
        background: var(--card-background-color);
        color: var(--primary-text-color);
        border-radius: 999px;
        padding: 6px 14px;
        cursor: pointer;
        font: inherit;
      }
      .tab.on {
        background: var(--primary-color);
        color: var(--text-primary-color);
        border-color: var(--primary-color);
      }
      .tab .n {
        opacity: 0.7;
        margin-left: 6px;
        font-size: 0.8em;
      }
      .meta {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin: 16px 0 8px;
        color: var(--secondary-text-color);
        font-size: 0.9rem;
      }
      .meta .actions button {
        background: none;
        border: none;
        color: var(--primary-color);
        cursor: pointer;
        font: inherit;
        margin-left: 12px;
      }
      .list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .list li {
        border-radius: 8px;
        padding: 8px 10px;
      }
      .list li.sel {
        background: color-mix(in srgb, var(--primary-color) 12%, transparent);
      }
      .list li.none {
        color: var(--secondary-text-color);
        text-align: center;
        padding: 24px;
      }
      .list label {
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
      }
      .nm {
        font-weight: 500;
      }
      .id {
        color: var(--secondary-text-color);
        font-size: 0.8rem;
        margin-left: auto;
        font-family: var(--code-font-family, monospace);
      }
      .err {
        color: var(--error-color);
        margin: 8px 0;
      }
      footer {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 20px;
        position: sticky;
        bottom: 0;
        background: var(--primary-background-color);
        padding: 12px 0;
      }
      .ok {
        color: var(--success-color, var(--primary-color));
      }
    `;
  }
}

customElements.define("koryx-remote-panel", KoryxRemotePanel);
