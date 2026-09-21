(function () {
  "use strict";

  const svg = (body) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

  // simboli in stile tavola di progetto, uno per impianto
  const SYSTEMS = {
    antincendio: { label: "Antincendio", icon: svg('<path d="M12 3c.5 3.2 4.5 5 4.5 10a4.5 4.5 0 0 1-9 0c0-2.2 1-3.6 2.2-4.8.2 1.6.9 2.3 1.8 2.6C11.3 8.6 11 6 12 3z"/>') },
    evac: { label: "EVAC", icon: svg('<path d="M4 9.5v5h3.5L13 19V5L7.5 9.5z"/><path d="M16 9a4.2 4.2 0 0 1 0 6M18.6 6.4a8 8 0 0 1 0 11.2"/>') },
    tvcc: { label: "TVCC", icon: svg('<rect x="3" y="7" width="12" height="10" rx="1.5"/><path d="M15 11l6-3v8l-6-3"/>') },
    antintrusione: { label: "Antintrusione", icon: svg('<rect x="5" y="11" width="14" height="9.5" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3M12 15v2.5"/>') },
    cablaggio: { label: "Cablaggio", icon: svg('<rect x="9.5" y="3" width="5" height="5" rx=".8"/><rect x="3" y="16" width="5" height="5" rx=".8"/><rect x="16" y="16" width="5" height="5" rx=".8"/><path d="M12 8v4M5.5 16v-4h13v4"/>') },
    bms: { label: "BMS / BACS", icon: svg('<path d="M5 21V6l7-3 7 3v15z"/><path d="M9 9.5h1.5M13.5 9.5H15M9 13h1.5M13.5 13H15M10 21v-4h4v4"/>') },
  };
  const EXTRA = {
    normativa: { label: "Normativa", icon: svg('<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/>') },
    tutte: { label: "Tutti", icon: svg('<rect x="4" y="4" width="6.5" height="6.5" rx="1"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1"/>') },
  };
  const ALL = { ...SYSTEMS, ...EXTRA };
  const PAGE_SIZE = 24;

  const data = window.NEWS_DATA || { updated: "", articles: [] };
  const articles = data.articles.slice().sort((a, b) => b.date.localeCompare(a.date));
  const byId = new Map(articles.map((a) => [a.id, a]));

  const $ = (id) => document.getElementById(id);
  const grid = $("grid"), moreBtn = $("more"), dialog = $("dialog"), sheet = $("sheet");
  const dateFmt = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", year: "numeric" });
  const dateTimeFmt = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

  const state = { filter: "tutte", query: "", shown: PAGE_SIZE };

  function el(tag, props, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    kids.flat().forEach((k) => k && node.append(k));
    return node;
  }

  // le icone sono stringhe SVG scritte qui sopra, mai testo che arriva dai feed
  function icon(id) {
    const t = document.createElement("template");
    t.innerHTML = (ALL[id] || ALL.normativa).icon;
    return t.content.firstChild;
  }

  function tint(node, id) {
    const key = ALL[id] ? id : "normativa";
    node.style.setProperty("--c", `var(--c-${key})`);
    node.style.setProperty("--on", `var(--on-${key})`);
    return node;
  }

  const primary = (a) => a.categories.find((c) => SYSTEMS[c]) || "normativa";
  const isNew = (a) => Date.now() - new Date(a.date) < 2 * 864e5;

  function relativeDate(iso) {
    const days = Math.floor((Date.now() - new Date(iso)) / 864e5);
    if (days <= 0) return "oggi";
    if (days === 1) return "ieri";
    if (days < 7) return `${days} giorni fa`;
    return dateFmt.format(new Date(iso));
  }

  function plate(id) {
    return tint(el("span", { class: "plate" }, icon(id), el("span", { text: ALL[id].label })), id);
  }

  function placeholder(id) {
    return el("div", { class: "ph" }, icon(id));
  }

  function image(a) {
    if (!a.image) return placeholder(primary(a));
    const img = el("img", { src: a.image, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => img.replaceWith(placeholder(primary(a))), { once: true });
    return img;
  }

  // ---------- legenda / filtri ----------
  function renderFilters() {
    const counts = { tutte: articles.length, normativa: articles.filter((a) => a.is_norm).length };
    for (const id of Object.keys(SYSTEMS)) counts[id] = articles.filter((a) => a.categories.includes(id)).length;
    const order = ["tutte", "normativa", ...Object.keys(SYSTEMS)];
    $("filters").replaceChildren(...order.map((id) => {
      const key = el("button", { class: "key", type: "button", "aria-pressed": String(id === state.filter) },
        icon(id), el("span", { text: ALL[id].label }), el("span", { class: "n", text: String(counts[id]) }));
      tint(key, id);
      key.addEventListener("click", () => { state.filter = id; state.shown = PAGE_SIZE; renderFilters(); renderGrid(); });
      return key;
    }));
  }

  function visible() {
    const q = state.query.trim().toLowerCase();
    return articles.filter((a) => {
      if (state.filter === "normativa" ? !a.is_norm : state.filter !== "tutte" && !a.categories.includes(state.filter)) return false;
      if (!q) return true;
      return [a.title, a.title_original, a.source, a.summary.join(" "), a.refs.join(" ")].join(" ").toLowerCase().includes(q);
    });
  }

  // ---------- elenco ----------
  function card(a) {
    const id = primary(a);
    const thumb = el("div", { class: "thumb" }, image(a), plate(id), isNew(a) ? el("span", { class: "flag", text: "Nuovo" }) : null);
    const refs = a.refs.length ? el("div", { class: "refs" }, a.refs.slice(0, 2).map((r) => el("span", { class: "ref", text: r }))) : null;
    const body = el("div", { class: "cbody" },
      el("h2", { text: a.title }),
      refs,
      el("p", { class: "meta" }, el("span", { text: a.source }), el("span", { text: relativeDate(a.date) })));
    return tint(el("a", { class: "card", href: `#${a.id}` }, thumb, body), id);
  }

  function renderGrid() {
    const list = visible();
    grid.replaceChildren(...list.slice(0, state.shown).map(card));
    $("empty").hidden = list.length > 0;
    moreBtn.hidden = list.length <= state.shown;
    $("count").textContent = list.length ? (list.length === 1 ? "1 articolo" : `${list.length} articoli`) : "";
  }

  // ---------- scheda ----------
  function openArticle(a) {
    tint(sheet, primary(a));
    $("d-cover").replaceChildren(image(a));
    const tags = a.categories.filter((c) => SYSTEMS[c]).map(plate);
    if (a.is_norm) tags.push(plate("normativa"));
    $("d-tags").replaceChildren(...tags);
    $("d-title").textContent = a.title;
    $("d-meta").replaceChildren(el("span", { text: a.source }), el("span", { text: dateFmt.format(new Date(a.date)) }));
    $("d-summary").replaceChildren(...a.summary.map((s) => el("li", { text: s })));
    const note = $("d-note");
    note.hidden = !a.translated;
    note.textContent = a.translated ? `Tradotto automaticamente dall’inglese. Titolo originale: ${a.title_original}` : "";
    $("d-refs-box").hidden = a.refs.length === 0;
    $("d-refs").replaceChildren(...a.refs.map((r) => el("span", { class: "ref", text: r })));
    const link = $("d-link");
    link.href = a.url;
    link.textContent = `Leggi l’articolo completo su ${a.source}`;
    if (!dialog.open) dialog.showModal();
    sheet.scrollTop = 0;
  }

  function syncFromHash() {
    const a = byId.get(location.hash.slice(1));
    if (a) openArticle(a);
    else if (dialog.open) dialog.close();
  }

  dialog.addEventListener("close", () => {
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  });
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  $("d-close").addEventListener("click", () => dialog.close());
  window.addEventListener("hashchange", syncFromHash);

  // ---------- avvio ----------
  $("search").addEventListener("input", (e) => { state.query = e.target.value; state.shown = PAGE_SIZE; renderGrid(); });
  moreBtn.addEventListener("click", () => { state.shown += PAGE_SIZE; renderGrid(); });

  $("updated").textContent = data.updated ? dateTimeFmt.format(new Date(data.updated)) : "in attesa dei primi dati";
  $("total").textContent = String(articles.length);
  renderFilters();
  renderGrid();
  syncFromHash();
})();
