/*
 * Zugangsübersicht – Dashboard-Karte der Integration HID Edge Solo.
 *
 * Eine Zeile je Mitglied, eine Spalte je Zugangssystem. Ein Klick auf ein
 * Mitglied öffnet einen Dialog, in dem sich der Zugang je System (oder in
 * allen Systemen) entfernen und fehlende Zugänge anlegen lassen.
 *
 * Personen verschiedener Systeme werden über den Namen zusammengeführt
 * (Groß-/Kleinschreibung und mehrfache Leerzeichen werden ignoriert).
 *
 * Minimal:
 *   type: custom:zugangs-uebersicht-card
 * Ohne "spalten" werden alle Sensoren "Zutrittsberechtigte" dieser
 * Integration als Spalten verwendet. Siehe README für alle Optionen.
 */

const CARD_VERSION = "0.0.4";
const DOMAIN = "hid_edge_solo";
const CARD_TAG = "zugangs-uebersicht-card";

const STATUS = {
  aktiv: { label: "Aktiv", icon: "mdi:check-circle", color: "var(--success-color, #43a047)", rank: 0 },
  vorhanden: { label: "Vorhanden", icon: "mdi:check-circle", color: "var(--success-color, #43a047)", rank: 0 },
  geplant: { label: "Geplant", icon: "mdi:clock-outline", color: "var(--info-color, #039be5)", rank: 1 },
  abgelaufen: { label: "Abgelaufen", icon: "mdi:clock-alert-outline", color: "var(--warning-color, #ffa000)", rank: 2 },
  kein_ausweis: { label: "Kein Ausweis", icon: "mdi:card-off-outline", color: "var(--warning-color, #ffa000)", rank: 3 },
  kein_zeitplan: { label: "Kein Zeitplan", icon: "mdi:calendar-remove-outline", color: "var(--warning-color, #ffa000)", rank: 3 },
};
const UNKNOWN_STATUS = { label: "Unbekannt", icon: "mdi:help-circle-outline", color: "var(--secondary-text-color)", rank: 4 };

const statusInfo = (s) => STATUS[s] || { ...UNKNOWN_STATUS, label: s ? String(s) : UNKNOWN_STATUS.label };
const isProblem = (s) => s !== "aktiv" && s !== "vorhanden";

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const norm = (s) => String(s ?? "").normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase("de");

const fmtDate = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString("de-DE");
};
const fmtDateTime = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? String(iso)
    : d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
};

/** Vor- und Nachname, notfalls aus dem Gesamtnamen (letztes Wort = Nachname). */
const splitName = (name) => {
  const parts = String(name || "").trim().split(/\s+/);
  if (parts.length < 2) return { vorname: parts[0] || "", nachname: "" };
  return { vorname: parts.slice(0, -1).join(" "), nachname: parts[parts.length - 1] };
};

/** Platzhalter {id}, {name}, ... in einer Aktion ersetzen. */
const fill = (template, vars) => {
  if (typeof template === "string") {
    const whole = template.match(/^\{(\w+)\}$/);
    if (whole) return vars[whole[1]] ?? "";
    return template.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
  }
  if (Array.isArray(template)) return template.map((t) => fill(t, vars));
  if (template && typeof template === "object") {
    return Object.fromEntries(Object.entries(template).map(([k, v]) => [k, fill(v, vars)]));
  }
  return template;
};

class ZugangsUebersichtCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._search = "";
    this._filter = "alle";
    this._dialog = null; // {type: "member", key} | {type: "new"}
    this._confirm = null; // "rm:<spalte>:<index>" | "rm:all"
    this._form = null; // {ci, vorname, nachname, zeitplan_id}
    this._busy = false;
    this._error = null;
    this._signature = null;
    this._onKey = (ev) => {
      if (ev.key === "Escape" && this._dialog && !this._busy) this._closeDialog();
    };
  }

  connectedCallback() {
    window.addEventListener("keydown", this._onKey);
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    if (config.spalten && !Array.isArray(config.spalten)) {
      throw new Error("'spalten' muss eine Liste sein");
    }
    this._config = { titel: "Zugangsübersicht", ...config };
    this._signature = null;
    if (this._hass) this._update(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._update(false);
  }

  getCardSize() {
    return 6;
  }

  // ------------------------------------------------------------ Daten

  _isHidList(eid) {
    const st = this._hass.states[eid];
    if (!st || !eid.startsWith("sensor.")) return false;
    const a = st.attributes;
    if (!Array.isArray(a.personen) || !("gesamt" in a)) return false;
    const platform = this._hass.entities?.[eid]?.platform;
    return platform ? platform === DOMAIN : "config_entry_id" in a;
  }

  _columns() {
    const hass = this._hass;
    let list = this._config.spalten;
    if (!list) {
      list = Object.keys(hass.states)
        .filter((eid) => this._isHidList(eid))
        .sort()
        .map((entity) => ({ entity }));
    }
    return list
      .map((c) => (typeof c === "string" ? { entity: c } : c))
      .filter((c) => c && c.entity)
      .map((c) => {
        const st = hass.states[c.entity];
        const a = st?.attributes || {};
        const hid = this._isHidList(c.entity);
        const entry = a.config_entry_id ? { config_entry_id: a.config_entry_id } : {};
        const devId = hass.entities?.[c.entity]?.device_id;
        const dev = devId ? hass.devices?.[devId] : null;
        const pick = (own, fallback) => (own === false ? null : own || fallback);
        return {
          entity: c.entity,
          name: c.name || dev?.name_by_user || dev?.name || a.controller || a.friendly_name || c.entity,
          state: st,
          attribut: c.attribut || "personen",
          entry_id: a.config_entry_id || "",
          zeitplaene: Array.isArray(a.zeitplaene) ? a.zeitplaene : [],
          entfernen: pick(
            c.entfernen,
            hid ? { action: `${DOMAIN}.delete_cardholder`, data: { ...entry, cardholder_id: "{id}" } } : null,
          ),
          hinzufuegen: pick(
            c.hinzufuegen,
            hid
              ? {
                  action: `${DOMAIN}.add_cardholder`,
                  data: { ...entry, forename: "{vorname}", surname: "{nachname}", schedule_id: "{zeitplan_id}" },
                }
              : null,
          ),
          aktualisieren: pick(
            c.aktualisieren,
            hid ? { action: `${DOMAIN}.refresh_cardholders`, data: { ...entry } } : null,
          ),
        };
      });
  }

  _rows(cols) {
    const map = new Map();
    cols.forEach((col, ci) => {
      const list = col.state?.attributes?.[col.attribut];
      if (!Array.isArray(list)) return;
      for (const raw of list) {
        const p = raw && typeof raw === "object" ? raw : { name: String(raw) };
        const name =
          String(p.name || `${p.vorname || ""} ${p.nachname || ""}`).trim() || `ID ${p.id ?? "?"}`;
        const key = norm(name);
        let row = map.get(key);
        if (!row) {
          row = { key, name, vorname: null, nachname: null, neu: false, cells: cols.map(() => []) };
          map.set(key, row);
        }
        if (!row.vorname && p.vorname) row.vorname = p.vorname;
        if (!row.nachname && p.nachname) row.nachname = p.nachname;
        if (p.neu) row.neu = true;
        row.cells[ci].push({ ...p, name, status: p.status || "vorhanden" });
      }
    });
    const sortKey = (r) => norm(`${r.nachname || splitName(r.name).nachname} ${r.vorname || splitName(r.name).vorname}`);
    return [...map.values()].sort((a, b) => sortKey(a).localeCompare(sortKey(b), "de"));
  }

  _bestStatus(entries) {
    return entries.reduce(
      (best, e) => (best === null || statusInfo(e.status).rank < statusInfo(best).rank ? e.status : best),
      null,
    );
  }

  _visibleRows(rows) {
    const q = norm(this._search);
    return rows.filter((r) => {
      if (q && !r.key.includes(q)) return false;
      switch (this._filter) {
        case "probleme":
          return r.cells.some((c) => c.some((e) => isProblem(e.status)));
        case "fehlt":
          return r.cells.some((c) => c.length === 0);
        case "neu":
          return r.neu;
        default:
          return true;
      }
    });
  }

  _canWrite() {
    if (this._config.nur_lesen) return false;
    return this._config.nur_admins === false || this._hass.user?.is_admin !== false;
  }

  // ------------------------------------------------------------ Darstellung

  _update(force) {
    if (!this._config || !this._hass) return;
    if (!this._built) this._build();
    const cols = this._columns();
    const sig = cols.map((c) => c.state).concat(cols.map((c) => c.name));
    const changed = force || !this._signature || sig.length !== this._signature.length || sig.some((s, i) => s !== this._signature[i]);
    if (!changed) return;
    this._signature = sig;
    this._cols = cols;
    this._allRows = this._rows(cols);
    this._renderContent();
    // Offenes Formular nicht überschreiben, sonst gehen Eingaben verloren
    if (!this._form) this._renderDialog();
  }

  _build() {
    this._built = true;
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <div class="title"></div>
          <div class="head-actions">
            <button class="icon-btn" data-action="refresh" title="Listen neu laden">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
            <button class="btn add-btn" data-action="new" title="Neue Person anlegen">
              <ha-icon icon="mdi:account-plus"></ha-icon><span>Person</span>
            </button>
          </div>
        </div>
        <div class="toolbar">
          <input class="search" type="search" placeholder="Mitglied suchen …" aria-label="Mitglied suchen">
          <select class="filter" aria-label="Filter">
            <option value="alle">Alle</option>
            <option value="probleme">Nicht aktiv</option>
            <option value="fehlt">Nicht überall</option>
            <option value="neu">Neu</option>
          </select>
        </div>
        <div class="content"></div>
      </ha-card>
      <div class="dialog-root"></div>`;
    const root = this.shadowRoot;
    root.querySelector(".search").addEventListener("input", (ev) => {
      this._search = ev.target.value;
      this._renderContent();
    });
    root.querySelector(".filter").addEventListener("change", (ev) => {
      this._filter = ev.target.value;
      this._renderContent();
    });
    root.addEventListener("click", (ev) => this._onClick(ev));
    root.addEventListener("keydown", (ev) => {
      if ((ev.key === "Enter" || ev.key === " ") && ev.target?.dataset?.action === "open") {
        ev.preventDefault();
        this._openMember(ev.target.dataset.key);
      }
    });
    root.addEventListener("input", (ev) => {
      const field = ev.target?.dataset?.field;
      if (field && this._form) this._form[field] = ev.target.value;
    });
    root.addEventListener("change", (ev) => {
      const field = ev.target?.dataset?.field;
      if (!field || !this._form) return;
      if (field === "ci") {
        this._form.ci = Number(ev.target.value);
        this._form.zeitplan_id = "";
        this._renderDialog();
      } else {
        this._form[field] = ev.target.value;
      }
    });
  }

  _renderContent() {
    const root = this.shadowRoot;
    const cols = this._cols || [];
    const write = this._canWrite();
    root.querySelector(".title").textContent = this._config.titel;
    root.querySelector(".add-btn").hidden = !write || !cols.some((c) => c.hinzufuegen);
    root.querySelector('[data-action="refresh"]').hidden = !cols.some((c) => c.aktualisieren);
    const content = root.querySelector(".content");

    if (!cols.length) {
      content.innerHTML = `<div class="empty">Keine Zugangssysteme gefunden. Ist die Integration HID Edge Solo
        eingerichtet? Alternativ die Spalten unter <code>spalten</code> angeben.</div>`;
      return;
    }

    const rows = this._visibleRows(this._allRows);
    const head = cols
      .map((c) => {
        const st = c.state;
        let sub;
        if (!st) sub = `<span class="warn">fehlt</span>`;
        else if (st.state === "unavailable" || st.state === "unknown") sub = `<span class="warn">nicht verfügbar</span>`;
        else {
          const list = st.attributes[c.attribut];
          const total = Array.isArray(list) ? list.length : 0;
          const active = Array.isArray(list) ? list.filter((p) => !isProblem(p?.status || "vorhanden")).length : 0;
          const warn = st.attributes.vollstaendig === false ? ` <span class="warn" title="Liste unvollständig">⚠</span>` : "";
          sub = `${active}/${total} aktiv${warn}`;
        }
        return `<th class="sys" title="${esc(c.entity)}"><div>${esc(c.name)}</div><div class="sub">${sub}</div></th>`;
      })
      .join("");

    const body = rows
      .map((r) => {
        const cells = r.cells
          .map((entries, ci) => {
            if (!entries.length) return `<td class="cell"><span class="none" title="Kein Zugang">–</span></td>`;
            const best = this._bestStatus(entries);
            const info = statusInfo(best);
            const until = entries.map((e) => fmtDate(e.gueltig_bis)).find(Boolean);
            const tip = `${cols[ci].name}: ${info.label}${until ? ` · bis ${until}` : ""}${entries.length > 1 ? ` · ${entries.length} Einträge` : ""}`;
            return `<td class="cell" title="${esc(tip)}"><ha-icon icon="${info.icon}" style="color:${info.color}"></ha-icon>${
              entries.length > 1 ? `<span class="count">×${entries.length}</span>` : ""
            }</td>`;
          })
          .join("");
        return `<tr class="row" data-action="open" data-key="${esc(r.key)}" tabindex="0">
          <td class="name">${esc(r.name)}${r.neu ? ` <span class="badge">neu</span>` : ""}</td>${cells}</tr>`;
      })
      .join("");

    const notes = [];
    for (const c of cols) {
      const a = c.state?.attributes || {};
      if (a.fehler) notes.push(`${esc(c.name)}: ${esc(a.fehler)}`);
    }
    const stand = cols
      .map((c) => c.state?.attributes?.stand)
      .filter(Boolean)
      .sort()[0];

    content.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th class="name">Mitglied <span class="sub">(${rows.length}/${this._allRows.length})</span></th>${head}</tr></thead>
          <tbody>${body || `<tr><td class="empty" colspan="${cols.length + 1}">Keine Mitglieder gefunden.</td></tr>`}</tbody>
        </table>
      </div>
      <div class="footer">
        <span class="legend">${["aktiv", "geplant", "abgelaufen", "kein_ausweis"]
          .map((s) => `<span><ha-icon icon="${STATUS[s].icon}" style="color:${STATUS[s].color}"></ha-icon>${STATUS[s].label}</span>`)
          .join("")}<span><span class="none">–</span> kein Zugang</span></span>
        ${stand ? `<span class="stand">Stand ${esc(fmtDateTime(stand))}</span>` : ""}
      </div>
      ${notes.length ? `<div class="notes">${notes.join("<br>")}</div>` : ""}`;
  }

  _renderDialog() {
    const host = this.shadowRoot.querySelector(".dialog-root");
    if (!this._dialog) {
      host.innerHTML = "";
      return;
    }
    const body = this._dialog.type === "new" ? this._newPersonBody() : this._memberBody();
    host.innerHTML = `
      <div class="overlay" data-action="overlay">
        <div class="dialog" role="dialog" aria-modal="true">
          ${body}
          ${this._error ? `<div class="error">${esc(this._error).replace(/\n/g, "<br>")}</div>` : ""}
        </div>
      </div>`;
    const first = host.querySelector("input[data-field]");
    if (first && this._form && !this._form.focused) {
      this._form.focused = true;
      first.focus();
    }
  }

  _dialogHead(title, sub) {
    return `<div class="d-head">
      <div><h2>${esc(title)}</h2>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
      <button class="icon-btn" data-action="close" title="Schließen" ${this._busy ? "disabled" : ""}>
        <ha-icon icon="mdi:close"></ha-icon></button>
    </div>`;
  }

  _memberBody() {
    const row = this._allRows.find((r) => r.key === this._dialog.key);
    const name = row?.name || this._dialog.name;
    if (!row) {
      return `${this._dialogHead(name)}<p>In keinem System mehr vorhanden.</p>
        <div class="d-actions"><button class="btn" data-action="close">Schließen</button></div>`;
    }
    const write = this._canWrite();
    const dis = this._busy ? "disabled" : "";
    const sections = this._cols
      .map((col, ci) => {
        const entries = row.cells[ci];
        let inner;
        if (entries.length) {
          inner = entries
            .map((e, idx) => {
              const info = statusInfo(e.status);
              const details = [
                e.zeitplan ? `Zeitplan: ${esc(e.zeitplan)}` : null,
                e.gueltig_bis ? `gültig bis ${esc(fmtDate(e.gueltig_bis))}` : null,
                typeof e.ausweise === "number" ? `${e.ausweise} Ausweis${e.ausweise === 1 ? "" : "e"}` : null,
                e.id != null && e.id !== "" ? `ID ${esc(e.id)}` : null,
              ].filter(Boolean);
              const token = `rm:${ci}:${idx}`;
              let action = "";
              if (write && col.entfernen) {
                action =
                  this._confirm === token
                    ? `<div class="confirm">Wirklich aus <b>${esc(col.name)}</b> entfernen?
                        <button class="btn danger" data-action="do-remove" data-ci="${ci}" data-idx="${idx}" ${dis}>Ja, entfernen</button>
                        <button class="btn" data-action="cancel" ${dis}>Abbrechen</button></div>`
                    : `<button class="btn danger-outline" data-action="ask" data-token="${token}" ${dis}>
                        <ha-icon icon="mdi:account-remove"></ha-icon>Entfernen</button>`;
              }
              return `<div class="entry">
                <div class="e-info"><span class="chip" style="--c:${info.color}"><ha-icon icon="${info.icon}"></ha-icon>${esc(info.label)}</span>
                <span class="details">${details.join(" · ")}</span></div>${action}</div>`;
            })
            .join("");
        } else {
          let add = "";
          if (write && col.hinzufuegen) {
            add =
              this._form && this._form.ci === ci
                ? this._addForm(col, false)
                : `<button class="btn" data-action="add-form" data-ci="${ci}" ${dis}><ha-icon icon="mdi:account-plus"></ha-icon>Zugang anlegen</button>`;
          }
          inner = `<div class="entry"><div class="e-info"><span class="none">–</span> <span class="details">kein Zugang</span></div>${add}</div>`;
        }
        return `<section><h3>${esc(col.name)}</h3>${inner}</section>`;
      })
      .join("");

    const removable = this._cols.reduce((n, col, ci) => n + (col.entfernen ? row.cells[ci].length : 0), 0);
    let all = "";
    if (write && removable > 1) {
      all =
        this._confirm === "rm:all"
          ? `<div class="confirm">${esc(name)} wirklich aus <b>allen Systemen</b> entfernen?
              <button class="btn danger" data-action="do-remove-all" ${dis}>Ja, überall entfernen</button>
              <button class="btn" data-action="cancel" ${dis}>Abbrechen</button></div>`
          : `<button class="btn danger" data-action="ask" data-token="rm:all" ${dis}>
              <ha-icon icon="mdi:account-cancel"></ha-icon>Aus allen Systemen entfernen</button>`;
    }
    const sub = row.neu ? `<span class="badge">neu</span>` : "";
    return `${this._dialogHead(name, sub)}${sections}
      ${all ? `<div class="d-actions">${all}</div>` : ""}
      ${this._busy ? `<div class="busy">Wird ausgeführt …</div>` : ""}`;
  }

  _addForm(col, withNames) {
    const f = this._form;
    const dis = this._busy ? "disabled" : "";
    const names = withNames
      ? `<label>Vorname<input data-field="vorname" value="${esc(f.vorname)}" maxlength="64" ${dis}></label>
         <label>Nachname<input data-field="nachname" value="${esc(f.nachname)}" maxlength="64" ${dis}></label>`
      : `<div class="details">Anlegen als <b>${esc(f.vorname)} ${esc(f.nachname)}</b></div>`;
    const schedules = col.zeitplaene.length
      ? `<label>Zeitplan<select data-field="zeitplan_id" ${dis}>
          <option value="">– ohne Zeitplan –</option>
          ${col.zeitplaene
            .map((z) => `<option value="${esc(z.id)}" ${String(z.id) === String(f.zeitplan_id) ? "selected" : ""}>${esc(z.name || `Zeitplan ${z.id}`)}</option>`)
            .join("")}
        </select></label>`
      : "";
    return `<div class="form">${names}${schedules}
      <div class="form-actions">
        <button class="btn primary" data-action="do-add" ${dis}><ha-icon icon="mdi:check"></ha-icon>Anlegen</button>
        ${withNames ? "" : `<button class="btn" data-action="cancel" ${dis}>Abbrechen</button>`}
      </div>
      <div class="hint">Ausweise (Kartennummern) werden am Controller zugewiesen.</div></div>`;
  }

  _newPersonBody() {
    const addable = this._cols.map((c, ci) => ({ c, ci })).filter(({ c }) => c.hinzufuegen);
    const f = this._form;
    const col = this._cols[f.ci];
    const system =
      addable.length > 1
        ? `<label>System<select data-field="ci" ${this._busy ? "disabled" : ""}>${addable
            .map(({ c, ci }) => `<option value="${ci}" ${ci === f.ci ? "selected" : ""}>${esc(c.name)}</option>`)
            .join("")}</select></label>`
        : `<div class="details">System: <b>${esc(col?.name)}</b></div>`;
    return `${this._dialogHead("Neue Person")}<section>${system}${col ? this._addForm(col, true) : ""}</section>
      ${this._busy ? `<div class="busy">Wird ausgeführt …</div>` : ""}`;
  }

  // ------------------------------------------------------------ Aktionen

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n instanceof HTMLElement && n.dataset?.action);
    if (!el) return;
    const action = el.dataset.action;
    if (el.disabled) return;
    switch (action) {
      case "open":
        this._openMember(el.dataset.key);
        break;
      case "overlay":
        if (ev.composedPath()[0] === el && !this._busy) this._closeDialog();
        break;
      case "close":
        this._closeDialog();
        break;
      case "ask":
        this._confirm = el.dataset.token;
        this._form = null;
        this._error = null;
        this._renderDialog();
        break;
      case "cancel":
        this._confirm = null;
        this._form = null;
        this._error = null;
        this._renderDialog();
        break;
      case "add-form": {
        const row = this._allRows.find((r) => r.key === this._dialog?.key);
        const split = splitName(row?.name);
        this._confirm = null;
        this._error = null;
        this._form = {
          ci: Number(el.dataset.ci),
          vorname: row?.vorname || split.vorname,
          nachname: row?.nachname || split.nachname,
          zeitplan_id: "",
          focused: true,
        };
        this._renderDialog();
        break;
      }
      case "do-remove":
        this._remove([[Number(el.dataset.ci), Number(el.dataset.idx)]]);
        break;
      case "do-remove-all": {
        const row = this._allRows.find((r) => r.key === this._dialog?.key);
        if (!row) break;
        const targets = [];
        this._cols.forEach((col, ci) => {
          if (col.entfernen) row.cells[ci].forEach((_, idx) => targets.push([ci, idx]));
        });
        this._remove(targets);
        break;
      }
      case "do-add":
        this._add();
        break;
      case "new": {
        const ci = this._cols.findIndex((c) => c.hinzufuegen);
        if (ci < 0) break;
        this._dialog = { type: "new" };
        this._confirm = null;
        this._error = null;
        this._form = { ci, vorname: "", nachname: "", zeitplan_id: "" };
        this._renderDialog();
        break;
      }
      case "refresh":
        this._refresh();
        break;
    }
  }

  _openMember(key) {
    const row = this._allRows.find((r) => r.key === key);
    if (!row) return;
    this._dialog = { type: "member", key, name: row.name };
    this._confirm = null;
    this._form = null;
    this._error = null;
    this._renderDialog();
  }

  _closeDialog() {
    this._dialog = null;
    this._confirm = null;
    this._form = null;
    this._error = null;
    this._renderDialog();
  }

  async _call(action, vars) {
    const a = fill(action, vars);
    const svc = a.action || a.service || a.perform_action;
    if (!svc || !svc.includes(".")) throw new Error(`Ungültige Aktion: ${svc}`);
    const [domain, service] = svc.split(".", 2);
    // Leere Platzhalter (z. B. ohne Zeitplan) weglassen
    const data = Object.fromEntries(Object.entries(a.data || {}).filter(([, v]) => v !== "" && v != null));
    return this._hass.callService(domain, service, data, a.target, false);
  }

  /** Mehrere Aufrufe nacheinander, Fehler sammeln statt abzubrechen. */
  async _runAll(calls) {
    this._busy = true;
    this._error = null;
    this._renderDialog();
    const failed = [];
    for (const { action, vars, label } of calls) {
      try {
        await this._call(action, vars);
      } catch (err) {
        failed.push(`${label}: ${err?.message || err}`);
      }
    }
    this._busy = false;
    this._confirm = null;
    this._error = failed.length ? failed.join("\n") : null;
    return failed.length === 0;
  }

  async _remove(targets) {
    const row = this._allRows.find((r) => r.key === this._dialog?.key);
    if (!row || !targets.length) return;
    const calls = targets.map(([ci, idx]) => {
      const col = this._cols[ci];
      const e = row.cells[ci][idx];
      const split = splitName(e.name);
      return {
        label: col.name,
        action: col.entfernen,
        vars: {
          id: e.id ?? "",
          name: e.name,
          vorname: e.vorname || split.vorname,
          nachname: e.nachname || split.nachname,
          config_entry_id: col.entry_id,
          entity: col.entity,
        },
      };
    });
    const ok = await this._runAll(calls);
    if (ok) {
      const where = calls.length > 1 ? "allen Systemen" : calls[0].label;
      this._toast(`${row.name} aus ${where} entfernt`);
    }
    this._update(true);
    this._renderDialog();
  }

  async _add() {
    const f = this._form;
    const col = f ? this._cols[f.ci] : null;
    if (!col || !col.hinzufuegen) return;
    const vorname = String(f.vorname || "").trim();
    const nachname = String(f.nachname || "").trim();
    if (!vorname || !nachname) {
      this._error = "Bitte Vor- und Nachname angeben.";
      this._renderDialog();
      return;
    }
    const zeitplan = col.zeitplaene.find((z) => String(z.id) === String(f.zeitplan_id));
    const ok = await this._runAll([
      {
        label: col.name,
        action: col.hinzufuegen,
        vars: {
          vorname,
          nachname,
          name: `${vorname} ${nachname}`,
          zeitplan_id: f.zeitplan_id || "",
          zeitplan: zeitplan?.name || "",
          config_entry_id: col.entry_id,
          entity: col.entity,
        },
      },
    ]);
    if (ok) {
      this._toast(`${vorname} ${nachname} in ${col.name} angelegt`);
      this._form = null;
      if (this._dialog?.type === "new") this._dialog = null;
    }
    this._update(true);
    this._renderDialog();
  }

  async _refresh() {
    const calls = this._cols
      .filter((c) => c.aktualisieren)
      .map((c) => ({ label: c.name, action: c.aktualisieren, vars: { config_entry_id: c.entry_id, entity: c.entity } }));
    const btn = this.shadowRoot.querySelector('[data-action="refresh"]');
    btn.disabled = true;
    btn.classList.add("spin");
    const failed = [];
    for (const { action, vars, label } of calls) {
      try {
        await this._call(action, vars);
      } catch (err) {
        failed.push(`${label}: ${err?.message || err}`);
      }
    }
    btn.disabled = false;
    btn.classList.remove("spin");
    this._toast(failed.length ? `Aktualisieren fehlgeschlagen – ${failed.join("; ")}` : "Listen aktualisiert");
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  [hidden] { display: none !important; }
  .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 16px 16px 8px; }
  .title { font-size: var(--ha-card-header-font-size, 24px); color: var(--ha-card-header-color, var(--primary-text-color)); line-height: 1.2; }
  .head-actions { display: flex; gap: 8px; align-items: center; }
  .toolbar { display: flex; gap: 8px; padding: 0 16px 8px; flex-wrap: wrap; }
  .toolbar .search { flex: 1 1 180px; min-width: 0; }
  input, select {
    font: inherit; color: var(--primary-text-color); background: var(--secondary-background-color, var(--card-background-color));
    border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px 10px; box-sizing: border-box;
  }
  input:focus, select:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  .table-wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; }
  th, td { padding: 8px 10px; border-bottom: 1px solid var(--divider-color); text-align: center; white-space: nowrap; }
  th { font-weight: 500; color: var(--secondary-text-color); position: sticky; top: 0; background: var(--card-background-color, var(--ha-card-background)); vertical-align: bottom; }
  th .sub, .sub { font-size: 0.8em; font-weight: 400; color: var(--secondary-text-color); }
  th.name, td.name { text-align: left; position: sticky; left: 0; background: var(--card-background-color, var(--ha-card-background)); z-index: 1; }
  td.name { color: var(--primary-text-color); white-space: normal; min-width: 140px; }
  tr.row { cursor: pointer; }
  tr.row:hover td, tr.row:focus td { background: var(--secondary-background-color); }
  tr.row:focus { outline: none; }
  tr.row:focus td.name { box-shadow: inset 3px 0 0 var(--primary-color); }
  td.cell ha-icon { --mdc-icon-size: 20px; }
  .count { font-size: 0.75em; color: var(--secondary-text-color); margin-left: 2px; vertical-align: top; }
  .none { color: var(--disabled-text-color, var(--secondary-text-color)); }
  .warn { color: var(--warning-color, #ffa000); }
  .badge { display: inline-block; font-size: 0.7em; padding: 1px 6px; border-radius: 8px; background: var(--primary-color); color: var(--text-primary-color, #fff); vertical-align: middle; }
  .empty { padding: 16px; color: var(--secondary-text-color); text-align: center; white-space: normal; }
  .footer { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 16px 12px; font-size: 0.8em; color: var(--secondary-text-color); }
  .legend { display: flex; gap: 12px; flex-wrap: wrap; }
  .legend span { display: inline-flex; align-items: center; gap: 3px; }
  .legend ha-icon { --mdc-icon-size: 16px; }
  .notes { padding: 0 16px 12px; font-size: 0.85em; color: var(--warning-color, #ffa000); }
  .btn, .icon-btn {
    font: inherit; font-size: 0.9em; cursor: pointer; border-radius: 8px; display: inline-flex; align-items: center; gap: 4px;
    border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); padding: 6px 10px;
  }
  .btn ha-icon { --mdc-icon-size: 18px; }
  .icon-btn { border: none; padding: 6px; border-radius: 50%; color: var(--secondary-text-color); }
  .icon-btn:hover, .btn:hover { background: var(--secondary-background-color); }
  .btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.danger { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color: #fff; }
  .btn.danger-outline { color: var(--error-color, #db4437); border-color: var(--error-color, #db4437); }
  .btn[disabled], .icon-btn[disabled] { opacity: 0.5; cursor: default; }
  .spin ha-icon { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .overlay { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,0.45); display: flex; align-items: center; justify-content: center; padding: 16px; box-sizing: border-box; }
  .dialog {
    background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color);
    border-radius: var(--ha-card-border-radius, 12px); width: min(520px, 100%); max-height: calc(100vh - 32px); overflow-y: auto;
    padding: 16px 20px 20px; box-sizing: border-box; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
  }
  .d-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
  h2 { margin: 4px 0; font-size: 1.3em; font-weight: 500; }
  section { border-top: 1px solid var(--divider-color); padding: 10px 0; }
  section:first-of-type { margin-top: 8px; }
  h3 { margin: 0 0 6px; font-size: 1em; font-weight: 500; }
  .entry { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 0; }
  .e-info { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
  .details { font-size: 0.85em; color: var(--secondary-text-color); }
  .chip { display: inline-flex; align-items: center; gap: 3px; font-size: 0.85em; padding: 2px 8px 2px 4px; border-radius: 12px;
    color: var(--c); border: 1px solid var(--c); }
  .chip ha-icon { --mdc-icon-size: 16px; }
  .confirm { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 0.9em; }
  .d-actions { border-top: 1px solid var(--divider-color); padding-top: 12px; display: flex; justify-content: flex-end; }
  .form { display: flex; flex-direction: column; gap: 8px; width: 100%; padding-top: 4px; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 0.85em; color: var(--secondary-text-color); }
  label input, label select { font-size: 1.1em; }
  .form-actions { display: flex; gap: 8px; }
  .hint { font-size: 0.8em; color: var(--secondary-text-color); }
  .error { margin-top: 12px; padding: 8px 10px; border-radius: 8px; color: var(--error-color, #db4437); background: rgba(219,68,55,0.1); font-size: 0.9em; }
  .busy { margin-top: 8px; font-size: 0.9em; color: var(--secondary-text-color); }
  code { font-family: var(--code-font-family, monospace); }
`;

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, ZugangsUebersichtCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "Zugangsübersicht",
    description: "Mitglieder je Zeile, Zugangssysteme je Spalte; Zugänge per Klick entfernen.",
    preview: false,
    documentationURL: "https://github.com/asfg-bremen/hid_edge_solo_ha",
  });
  console.info(`%c ZUGANGS-UEBERSICHT-CARD %c ${CARD_VERSION} `, "background:#1565c0;color:#fff", "background:#ddd;color:#000");
}
