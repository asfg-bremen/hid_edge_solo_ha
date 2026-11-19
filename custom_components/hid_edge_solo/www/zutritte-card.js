/*
 * Zutritte – Dashboard-Karte der Integration HID Edge Solo.
 *
 * Alle Zutritte der Bereiche (Türen) in einer Liste, neueste zuerst.
 * Oben eine Zeitleiste mit den letzten Tagen (Klick filtert auf den Tag),
 * darunter Personensuche, Bereiche zum An-/Abschalten und ein Zeitfilter.
 *
 * Die Sensoren "Letzter Zutritt" liefern je Tür die letzten 20 Zutritte.
 * Weiter zurück lädt die Karte über den Dienst hid_edge_solo.get_events.
 *
 * Minimal:
 *   type: custom:zutritte-card
 * Kompakt (z. B. in der Übersicht, nur die letzten Zutritte einer Tür):
 *   type: custom:zutritte-card
 *   kompakt: true
 *   bereiche: [sensor.neue_halle_letzter_zutritt]
 */

const CARD_VERSION = "0.0.6";
const DOMAIN = "hid_edge_solo";
const CARD_TAG = "zutritte-card";
const GRANTED = "Zutritt gewährt";

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const norm = (s) => String(s ?? "").normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase("de");

const pad = (n) => String(n).padStart(2, "0");
const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const WD = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
const fmtTime = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const fmtShortDate = (d) => `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.`;
const fmtDayTitle = (d) =>
  d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
/** Wert für <input type="datetime-local"> */
const toLocalInput = (d) =>
  d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${fmtTime(d)}` : "";
const fromLocalInput = (v) => {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
};
const relDay = (d, now = new Date()) => {
  const diff = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (diff === 0) return "heute";
  if (diff === 1) return "gestern";
  return `${WD[d.getDay()]} ${fmtShortDate(d)}`;
};

class ZutritteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._search = "";
    this._off = new Set(); // abgeschaltete Bereiche (Entitäts-IDs)
    this._day = null; // "YYYY-MM-DD"
    this._von = null;
    this._bis = null;
    this._sort = { key: "t", dir: -1 };
    this._limit = 100;
    this._loaded = {}; // entity -> {events, error, complete}
    this._loading = false;
    this._loadedOnce = false;
    this._signature = null;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    if (config.bereiche && !Array.isArray(config.bereiche)) {
      throw new Error("'bereiche' muss eine Liste sein");
    }
    this._config = {
      titel: config.kompakt ? "Letzte Zutritte" : "Zutritte",
      tage: 14,
      anzahl: 200,
      max_zeilen: 5,
      ...config,
    };
    this._built = false;
    this._signature = null;
    if (this._hass) this._update(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._update(false);
  }

  getCardSize() {
    return this._config?.kompakt ? 3 : 8;
  }

  // ------------------------------------------------------------ Daten

  _isHidAccess(eid) {
    const st = this._hass.states[eid];
    if (!st || !eid.startsWith("sensor.") || !Array.isArray(st.attributes.verlauf)) return false;
    const platform = this._hass.entities?.[eid]?.platform;
    return platform ? platform === DOMAIN : "config_entry_id" in st.attributes;
  }

  _areas() {
    const hass = this._hass;
    let list = this._config.bereiche;
    if (!list) {
      list = Object.keys(hass.states)
        .filter((eid) => this._isHidAccess(eid))
        .sort()
        .map((entity) => ({ entity }));
    }
    return list
      .map((b) => (typeof b === "string" ? { entity: b } : b))
      .filter((b) => b && b.entity)
      .map((b) => {
        const st = hass.states[b.entity];
        const a = st?.attributes || {};
        const devId = hass.entities?.[b.entity]?.device_id;
        const dev = devId ? hass.devices?.[devId] : null;
        return {
          entity: b.entity,
          name: b.name || dev?.name_by_user || dev?.name || a.controller || a.friendly_name || b.entity,
          state: st,
          entry_id: a.config_entry_id || "",
          verlauf: Array.isArray(a.verlauf) ? a.verlauf : [],
        };
      });
  }

  /** Verlauf der Sensoren und nachgeladene Ereignisse zusammenführen. */
  _events(areas) {
    const all = [];
    areas.forEach((area, ai) => {
      const seen = new Set();
      const loaded = this._loaded[area.entity]?.events || [];
      for (const e of [...area.verlauf, ...loaded]) {
        if (!e || !e.zeit) continue;
        const key = `${e.zeit}|${e.name}|${e.ereignis}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const d = new Date(e.zeit);
        if (Number.isNaN(d.getTime())) continue;
        all.push({ t: d.getTime(), d, name: e.name || "Unbekannt", ereignis: e.ereignis || "", ai });
      }
    });
    return all;
  }

  /** Ab wann je Bereich lückenlos Daten vorliegen (null = alles da). */
  _coverage(areas, events) {
    return areas.map((area, ai) => {
      const loaded = this._loaded[area.entity];
      if (loaded?.complete) return null;
      const own = events.filter((e) => e.ai === ai);
      if (!own.length) return null;
      return Math.min(...own.map((e) => e.t));
    });
  }

  _canLoad() {
    return !!this._hass.services?.[DOMAIN]?.get_events && Number(this._config.anzahl) > 0;
  }

  async _load() {
    if (this._loading || !this._canLoad()) return;
    const areas = (this._areas_cache || this._areas()).filter((a) => a.entry_id);
    if (!areas.length) return;
    this._loading = true;
    this._renderStatus();
    const anzahl = Math.min(500, Math.max(1, Number(this._config.anzahl) || 200));
    await Promise.all(
      areas.map(async (area) => {
        try {
          const res = await this._hass.callWS({
            type: "call_service",
            domain: DOMAIN,
            service: "get_events",
            service_data: { config_entry_id: area.entry_id, anzahl },
            return_response: true,
          });
          const events = res?.response?.ereignisse || [];
          this._loaded[area.entity] = { events, error: null, complete: events.length < anzahl };
        } catch (err) {
          const prev = this._loaded[area.entity];
          this._loaded[area.entity] = {
            events: prev?.events || [],
            error: err?.message || String(err),
            complete: prev?.complete || false,
          };
        }
      }),
    );
    this._loading = false;
    this._render();
  }

  // ------------------------------------------------------------ Filter

  _range() {
    if (this._day) {
      const [y, m, d] = this._day.split("-").map(Number);
      const from = new Date(y, m - 1, d);
      return [from.getTime(), new Date(y, m - 1, d + 1).getTime() - 1];
    }
    return [this._von ? this._von.getTime() : -Infinity, this._bis ? this._bis.getTime() : Infinity];
  }

  /** Personen- und Bereichsfilter (ohne Zeit, für die Zeitleiste). */
  _baseFilter(events, areas) {
    const q = norm(this._search);
    return events.filter((e) => !this._off.has(areas[e.ai].entity) && (!q || norm(e.name).includes(q)));
  }

  // ------------------------------------------------------------ Darstellung

  _update(force) {
    if (!this._config || !this._hass) return;
    const areas = this._areas();
    const sig = areas.map((a) => a.state).concat(areas.map((a) => a.name));
    const changed =
      force || !this._signature || sig.length !== this._signature.length || sig.some((s, i) => s !== this._signature[i]);
    if (!changed) return;
    this._signature = sig;
    this._areas_cache = areas;
    if (!this._built) this._build();
    this._render();
    if (!this._config.kompakt && !this._loadedOnce && this._canLoad()) {
      this._loadedOnce = true;
      this._load();
    }
  }

  _build() {
    this._built = true;
    const kompakt = !!this._config.kompakt;
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card class="${kompakt ? "kompakt" : ""}">
        <div class="header">
          <div class="title">${esc(this._config.titel)}</div>
          ${
            kompakt
              ? ""
              : `<div class="head-actions">
                  <span class="status"></span>
                  <button class="icon-btn" data-action="reload" title="Vom Controller nachladen"><ha-icon icon="mdi:refresh"></ha-icon></button>
                </div>`
          }
        </div>
        ${
          kompakt
            ? ""
            : `<div class="timeline" role="group" aria-label="Tage"></div>
               <div class="toolbar">
                 <input class="search" type="search" placeholder="Person suchen …" aria-label="Person suchen">
                 <label class="range">von <input class="von" type="datetime-local"></label>
                 <label class="range">bis <input class="bis" type="datetime-local"></label>
                 <button class="btn reset" data-action="reset" title="Alle Filter zurücksetzen"><ha-icon icon="mdi:filter-remove-outline"></ha-icon>Zurücksetzen</button>
               </div>
               <div class="chips" role="group" aria-label="Bereiche"></div>
               <div class="summary"></div>`
        }
        <div class="list"></div>
        <div class="notes"></div>
      </ha-card>`;
    const root = this.shadowRoot;
    root.addEventListener("click", (ev) => this._onClick(ev));
    if (kompakt) return;
    root.querySelector(".search").addEventListener("input", (ev) => {
      this._search = ev.target.value;
      this._limit = 100;
      this._render();
    });
    root.querySelector(".von").addEventListener("change", (ev) => {
      this._von = fromLocalInput(ev.target.value);
      this._day = null;
      this._limit = 100;
      this._render();
    });
    root.querySelector(".bis").addEventListener("change", (ev) => {
      this._bis = fromLocalInput(ev.target.value);
      this._day = null;
      this._limit = 100;
      this._render();
    });
  }

  _render() {
    const areas = this._areas_cache || [];
    const events = this._events(areas);
    if (this._config.kompakt) {
      this._renderCompact(areas, events);
      return;
    }
    const base = this._baseFilter(events, areas);
    const coverage = this._coverage(areas, events);
    this._renderTimeline(areas, base, coverage);
    this._renderChips(areas, events);
    this._renderInputs();
    const [from, to] = this._range();
    const rows = base.filter((e) => e.t >= from && e.t <= to);
    this._renderList(areas, rows);
    this._renderSummary(rows);
    this._renderNotes(areas, coverage);
    this._renderStatus();
  }

  _renderStatus() {
    const st = this.shadowRoot.querySelector(".status");
    const btn = this.shadowRoot.querySelector('[data-action="reload"]');
    if (!st || !btn) return;
    st.textContent = this._loading ? "lädt …" : "";
    btn.disabled = this._loading;
    btn.hidden = !this._canLoad();
    btn.classList.toggle("spin", this._loading);
  }

  _renderInputs() {
    const root = this.shadowRoot;
    const von = root.querySelector(".von");
    const bis = root.querySelector(".bis");
    if (this._day) {
      const [from, to] = this._range();
      von.value = toLocalInput(new Date(from));
      bis.value = toLocalInput(new Date(to));
    } else {
      if (root.activeElement !== von) von.value = toLocalInput(this._von);
      if (root.activeElement !== bis) bis.value = toLocalInput(this._bis);
    }
    const active = this._search || this._day || this._von || this._bis || this._off.size;
    root.querySelector(".reset").hidden = !active;
  }

  _renderTimeline(areas, base, coverage) {
    const tage = Math.max(1, Math.min(60, Number(this._config.tage) || 14));
    const today = startOfDay(new Date());
    const counts = new Map();
    for (const e of base) {
      const k = dayKey(e.d);
      counts.set(k, (counts.get(k) || 0) + 1);
    }
    // Lückenlos ab dem spätesten Datenbeginn der eingeschalteten Bereiche
    const starts = coverage.filter((c, i) => c !== null && !this._off.has(areas[i].entity));
    const fullFrom = starts.length ? Math.max(...starts) : -Infinity;
    const days = [];
    for (let i = tage - 1; i >= 0; i--) days.push(new Date(today.getFullYear(), today.getMonth(), today.getDate() - i));
    const max = Math.max(1, ...days.map((d) => counts.get(dayKey(d)) || 0));
    this.shadowRoot.querySelector(".timeline").innerHTML = days
      .map((d) => {
        const k = dayKey(d);
        const n = counts.get(k) || 0;
        const endOfDay = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime() - 1;
        const partial = endOfDay < fullFrom || (d.getTime() < fullFrom && endOfDay >= fullFrom);
        const noData = endOfDay < fullFrom;
        const h = n ? Math.max(8, Math.round((n / max) * 100)) : 0;
        const cls = ["day", k === this._day ? "sel" : "", d.getDay() === 0 || d.getDay() === 6 ? "we" : "", noData ? "nodata" : ""]
          .filter(Boolean)
          .join(" ");
        const tip = `${fmtDayTitle(d)}: ${n} Zutritt${n === 1 ? "" : "e"}${partial ? " (Daten unvollständig)" : ""}`;
        return `<button class="${cls}" data-action="day" data-day="${k}" title="${esc(tip)}" aria-pressed="${k === this._day}">
            <span class="n">${n || ""}</span>
            <span class="bar-wrap"><span class="bar" style="height:${h}%"></span></span>
            <span class="wd">${d.getTime() === today.getTime() ? "Heute" : WD[d.getDay()]}</span>
            <span class="dt">${fmtShortDate(d)}</span>
          </button>`;
      })
      .join("");
    // Heute sichtbar halten
    const tl = this.shadowRoot.querySelector(".timeline");
    if (!this._tlScrolled) {
      this._tlScrolled = true;
      requestAnimationFrame(() => (tl.scrollLeft = tl.scrollWidth));
    }
  }

  _renderChips(areas, events) {
    const counts = areas.map((_, ai) => events.filter((e) => e.ai === ai).length);
    this.shadowRoot.querySelector(".chips").innerHTML =
      areas.length > 1
        ? areas
            .map((a, ai) => {
              const on = !this._off.has(a.entity);
              return `<button class="chip ${on ? "on" : ""}" data-action="area" data-entity="${esc(a.entity)}" aria-pressed="${on}" title="${on ? "Ausblenden" : "Einblenden"}">
                <ha-icon icon="${on ? "mdi:check" : "mdi:close"}"></ha-icon>${esc(a.name)} <span class="cnt">${counts[ai]}</span></button>`;
            })
            .join("") + `<button class="link" data-action="areas-all">alle</button>`
        : "";
  }

  _renderSummary(rows) {
    const parts = [`<b>${rows.length}</b> Zutritt${rows.length === 1 ? "" : "e"}`];
    if (this._day) {
      const [y, m, d] = this._day.split("-").map(Number);
      parts.push(`am ${esc(fmtDayTitle(new Date(y, m - 1, d)))}`);
    } else if (this._von || this._bis) {
      if (this._von) parts.push(`ab ${esc(this._von.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }))}`);
      if (this._bis) parts.push(`bis ${esc(this._bis.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }))}`);
    }
    if (this._search) parts.push(`für „${esc(this._search)}“`);
    this.shadowRoot.querySelector(".summary").innerHTML = parts.join(" ");
  }

  _sortRows(rows, areas) {
    const { key, dir } = this._sort;
    const val = (e) => (key === "t" ? e.t : key === "bereich" ? norm(areas[e.ai].name) : norm(e[key]));
    return [...rows].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (va < vb) return -dir;
      if (va > vb) return dir;
      return b.t - a.t;
    });
  }

  _renderList(areas, rows) {
    const list = this.shadowRoot.querySelector(".list");
    if (!rows.length) {
      list.innerHTML = `<div class="empty">Keine Zutritte gefunden.</div>`;
      return;
    }
    const sorted = this._sortRows(rows, areas);
    const shown = sorted.slice(0, this._limit);
    const arrow = (k) => (this._sort.key === k ? (this._sort.dir < 0 ? " ▼" : " ▲") : "");
    const th = (k, label) =>
      `<th data-action="sort" data-key="${k}" aria-sort="${this._sort.key === k ? (this._sort.dir < 0 ? "descending" : "ascending") : "none"}">${label}${arrow(k)}</th>`;
    let lastDay = null;
    const body = shown
      .map((e) => {
        let sep = "";
        if (this._sort.key === "t") {
          const k = dayKey(e.d);
          if (k !== lastDay) {
            lastDay = k;
            sep = `<tr class="sep"><td colspan="4">${esc(fmtDayTitle(e.d))}</td></tr>`;
          }
        }
        const other = e.ereignis && e.ereignis !== GRANTED;
        return `${sep}<tr class="${other ? "other" : ""}">
          <td class="time">${this._sort.key === "t" ? "" : `${WD[e.d.getDay()]} ${fmtShortDate(e.d)} `}${fmtTime(e.d)}</td>
          <td>${esc(areas[e.ai].name)}</td>
          <td><button class="link person" data-action="person" data-name="${esc(e.name)}" title="Nur ${esc(e.name)} anzeigen">${esc(e.name)}</button></td>
          <td class="ev">${esc(e.ereignis)}</td></tr>`;
      })
      .join("");
    list.innerHTML = `<div class="table-wrap"><table>
      <thead><tr>${th("t", "Zeit")}${th("bereich", "Bereich")}${th("name", "Person")}${th("ereignis", "Ereignis")}</tr></thead>
      <tbody>${body}</tbody></table></div>
      ${sorted.length > shown.length ? `<div class="more"><button class="btn" data-action="more">Weitere ${Math.min(100, sorted.length - shown.length)} anzeigen (${sorted.length - shown.length} übrig)</button></div>` : ""}`;
  }

  _renderNotes(areas, coverage) {
    const notes = [];
    areas.forEach((a, ai) => {
      if (!a.state) notes.push(`${esc(a.name)}: Entität ${esc(a.entity)} fehlt`);
      else if (a.state.state === "unavailable") notes.push(`${esc(a.name)}: nicht verfügbar`);
      const err = this._loaded[a.entity]?.error;
      if (err) notes.push(`${esc(a.name)}: Nachladen fehlgeschlagen (${esc(err)}), nur die letzten 20 Zutritte`);
    });
    const from = areas
      .map((a, ai) => (coverage[ai] ? `${esc(a.name)} ab ${esc(relDay(new Date(coverage[ai])))} ${fmtTime(new Date(coverage[ai]))}` : null))
      .filter(Boolean);
    const el = this.shadowRoot.querySelector(".notes");
    el.innerHTML = [
      from.length ? `<div>Daten liegen vor: ${from.join(" · ")}</div>` : "",
      notes.length ? `<div class="warn">${notes.join("<br>")}</div>` : "",
    ].join("");
  }

  _renderCompact(areas, events) {
    const n = Math.max(1, Number(this._config.max_zeilen) || 5);
    const rows = [...events].sort((a, b) => b.t - a.t).slice(0, n);
    const multi = areas.length > 1;
    const now = new Date();
    this.shadowRoot.querySelector(".list").innerHTML = rows.length
      ? `<ul class="compact">${rows
          .map(
            (e) => `<li class="${e.ereignis && e.ereignis !== GRANTED ? "other" : ""}">
              <span class="when" title="${esc(e.d.toLocaleString("de-DE"))}">${esc(relDay(e.d, now))} ${fmtTime(e.d)}</span>
              <span class="who">${esc(e.name)}${e.ereignis && e.ereignis !== GRANTED ? ` <span class="ev">· ${esc(e.ereignis)}</span>` : ""}</span>
              ${multi ? `<span class="where">${esc(areas[e.ai].name)}</span>` : ""}
            </li>`,
          )
          .join("")}</ul>`
      : `<div class="empty">${areas.some((a) => a.state?.state === "unavailable") ? "Nicht verfügbar" : "Keine Zutritte"}</div>`;
  }

  // ------------------------------------------------------------ Aktionen

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n instanceof HTMLElement && n.dataset?.action);
    if (!el || el.disabled) return;
    const areas = this._areas_cache || [];
    switch (el.dataset.action) {
      case "day":
        this._day = this._day === el.dataset.day ? null : el.dataset.day;
        this._von = null;
        this._bis = null;
        break;
      case "area": {
        const eid = el.dataset.entity;
        if (this._off.has(eid)) this._off.delete(eid);
        else this._off.add(eid);
        // Mindestens ein Bereich bleibt an
        if (this._off.size >= areas.length) this._off.delete(eid);
        break;
      }
      case "areas-all":
        this._off.clear();
        break;
      case "person":
        this._search = el.dataset.name;
        this.shadowRoot.querySelector(".search").value = this._search;
        break;
      case "sort": {
        const key = el.dataset.key;
        this._sort = this._sort.key === key ? { key, dir: -this._sort.dir } : { key, dir: key === "t" ? -1 : 1 };
        break;
      }
      case "more":
        this._limit += 100;
        break;
      case "reset":
        this._search = "";
        this._day = null;
        this._von = null;
        this._bis = null;
        this._off.clear();
        this._sort = { key: "t", dir: -1 };
        this.shadowRoot.querySelector(".search").value = "";
        break;
      case "reload":
        this._load();
        return;
      default:
        return;
    }
    if (el.dataset.action !== "more") this._limit = 100;
    this._render();
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  [hidden] { display: none !important; }
  .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 16px 16px 8px; }
  .kompakt .header { padding: 12px 16px 4px; }
  .title { font-size: var(--ha-card-header-font-size, 24px); color: var(--ha-card-header-color, var(--primary-text-color)); line-height: 1.2; }
  .kompakt .title { font-size: 1.1em; font-weight: 500; }
  .head-actions { display: flex; align-items: center; gap: 8px; color: var(--secondary-text-color); font-size: 0.85em; }
  .timeline { display: flex; gap: 4px; overflow-x: auto; padding: 4px 16px 8px; scrollbar-width: thin; }
  .day {
    flex: 1 0 44px; max-width: 72px; display: flex; flex-direction: column; align-items: center; gap: 2px;
    border: 1px solid transparent; border-radius: 10px; background: var(--secondary-background-color, rgba(0,0,0,0.04));
    padding: 4px 2px 6px; cursor: pointer; font: inherit; color: var(--primary-text-color);
  }
  .day:hover { border-color: var(--divider-color); }
  .day.sel { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .day.sel .bar { background: var(--text-primary-color, #fff); }
  .day.we .wd { color: var(--secondary-text-color); }
  .day.sel.we .wd { color: inherit; }
  .day.nodata { opacity: 0.45; background-image: repeating-linear-gradient(45deg, transparent 0 4px, rgba(127,127,127,0.12) 4px 8px); }
  .n { font-size: 0.75em; min-height: 1.1em; }
  .bar-wrap { height: 44px; width: 14px; display: flex; align-items: flex-end; }
  .bar { width: 100%; border-radius: 4px 4px 2px 2px; background: var(--primary-color); }
  .wd { font-size: 0.8em; font-weight: 500; }
  .dt { font-size: 0.7em; color: var(--secondary-text-color); }
  .day.sel .dt { color: inherit; }
  .toolbar { display: flex; gap: 8px; padding: 0 16px 8px; flex-wrap: wrap; align-items: center; }
  .toolbar .search { flex: 1 1 180px; min-width: 0; }
  .range { display: inline-flex; align-items: center; gap: 4px; font-size: 0.85em; color: var(--secondary-text-color); }
  input {
    font: inherit; color: var(--primary-text-color); background: var(--secondary-background-color, var(--card-background-color));
    border: 1px solid var(--divider-color); border-radius: 8px; padding: 7px 10px; box-sizing: border-box; min-width: 0;
  }
  input:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; padding: 0 16px 8px; align-items: center; }
  .chip {
    font: inherit; font-size: 0.9em; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;
    border-radius: 16px; padding: 4px 12px 4px 8px; border: 1px solid var(--divider-color);
    background: transparent; color: var(--secondary-text-color);
  }
  .chip ha-icon { --mdc-icon-size: 16px; }
  .chip.on { background: rgba(var(--rgb-primary-color, 3,169,244), 0.15); border-color: var(--primary-color); color: var(--primary-text-color); }
  .chip .cnt { font-size: 0.8em; color: var(--secondary-text-color); }
  .summary { padding: 0 16px 6px; font-size: 0.9em; color: var(--secondary-text-color); }
  .table-wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; }
  th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--divider-color); white-space: nowrap; }
  th { font-weight: 500; color: var(--secondary-text-color); cursor: pointer; user-select: none; position: sticky; top: 0; background: var(--card-background-color, var(--ha-card-background)); }
  th:hover { color: var(--primary-text-color); }
  td.time { font-variant-numeric: tabular-nums; color: var(--secondary-text-color); }
  tr.sep td { background: var(--secondary-background-color); font-weight: 500; font-size: 0.85em; color: var(--secondary-text-color); padding: 4px 10px; }
  tr.other td.ev { color: var(--warning-color, #ffa000); }
  td.ev { color: var(--secondary-text-color); }
  .link { font: inherit; background: none; border: none; padding: 0; color: inherit; cursor: pointer; text-align: left; }
  .link:hover { color: var(--primary-color); text-decoration: underline; }
  .chips .link { font-size: 0.85em; color: var(--secondary-text-color); }
  .btn, .icon-btn {
    font: inherit; font-size: 0.9em; cursor: pointer; border-radius: 8px; display: inline-flex; align-items: center; gap: 4px;
    border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); padding: 6px 10px;
  }
  .btn ha-icon { --mdc-icon-size: 18px; }
  .icon-btn { border: none; padding: 6px; border-radius: 50%; color: var(--secondary-text-color); }
  .icon-btn:hover, .btn:hover { background: var(--secondary-background-color); }
  .icon-btn[disabled] { opacity: 0.5; cursor: default; }
  .spin ha-icon { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .more { padding: 8px 16px; text-align: center; }
  .empty { padding: 16px; color: var(--secondary-text-color); text-align: center; }
  .kompakt .empty { padding: 8px 16px 16px; text-align: left; }
  .notes { padding: 6px 16px 12px; font-size: 0.8em; color: var(--secondary-text-color); }
  .notes:empty { display: none; }
  .warn { color: var(--warning-color, #ffa000); margin-top: 4px; }
  ul.compact { list-style: none; margin: 0; padding: 0 16px 12px; }
  ul.compact li { display: flex; gap: 10px; align-items: baseline; padding: 4px 0; border-bottom: 1px solid var(--divider-color); }
  ul.compact li:last-child { border-bottom: none; }
  .when { flex: 0 0 auto; min-width: 92px; font-size: 0.85em; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .who { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .who .ev, li.other .ev { color: var(--warning-color, #ffa000); font-size: 0.85em; }
  .where { flex: 0 0 auto; font-size: 0.8em; color: var(--secondary-text-color); }
`;

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, ZutritteCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "Zutritte",
    description: "Zutritte aller Türen mit Zeitleiste, Personensuche, Bereichs- und Zeitfilter.",
    preview: false,
    documentationURL: "https://github.com/asfg-bremen/hid_edge_solo_ha",
  });
  console.info(`%c ZUTRITTE-CARD %c ${CARD_VERSION} `, "background:#1565c0;color:#fff", "background:#ddd;color:#000");
}
