(function () {
  "use strict";

  const CATEGORIES = {
    antincendio: "Antincendio",
    evac: "EVAC",
    tvcc: "TVCC",
    antintrusione: "Antintrusione",
    cablaggio: "Cablaggio",
    bms: "BMS / BACS",
  };
  const PAGE_SIZE = 24;

  const data = window.NEWS_DATA || { updated: "", articles: [] };
  const articles = data.articles.slice().sort((a, b) => b.date.localeCompare(a.date));
  const byId = new Map(articles.map((a) => [a.id, a]));

  const $ = (id) => document.getElementById(id);
  const grid = $("grid"), moreBtn = $("more"), dialog = $("dialog");
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

  const primaryCategory = (a) => a.categories[0] || "";
  const catVar = (id) => `var(--c-${id || "default"})`;
  const label = (id) => (id === "normativa" ? "Normativa" : CATEGORIES[id] || "Impianti speciali");

  function relativeDate(iso) {
    const days = Math.floor((Date.now() - new Date(iso)) / 864e5);
    if (days <= 0) return "oggi";
    if (days === 1) return "ieri";
    if (days < 7) return `${days} giorni fa`;
    return dateFmt.format(new Date(iso));
  }
  const isNew = (a) => Date.now() - new Date(a.date) < 2 * 864e5;

  function placeholder(a) {
    const ph = el("div", { class: "ph", text: label(primaryCategory(a)) });
    ph.style.setProperty("--c", catVar(primaryCategory(a)));
    return ph;
  }

  function image(a) {
    if (!a.image) return placeholder(a);
    const img = el("img", { src: a.image, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => img.replaceWith(placeholder(a)), { once: true });
    return img;
  }

  function badge(id) {
    const b = el("span", { class: "badge", text: label(id) });
    b.style.setProperty("--c", catVar(id));
    return b;
  }

  // ---------- filtri ----------
  function renderFilters() {
    const counts = { tutte: articles.length, normativa: articles.filter((a) => a.is_norm).length };
    for (const id of Object.keys(CATEGORIES)) counts[id] = articles.filter((a) => a.categories.includes(id)).length;
    const items = [["tutte", "Tutte"], ["normativa", "Normativa"], ...Object.entries(CATEGORIES)];
    const box = $("filters");
    box.replaceChildren(...items.map(([id, name]) => {
      const chip = el("button", { class: "chip", type: "button", "aria-pressed": String(id === state.filter), text: `${name} · ${counts[id]}` });
      chip.addEventListener("click", () => { state.filter = id; state.shown = PAGE_SIZE; renderFilters(); renderGrid(); });
      return chip;
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

  // ---------- griglia ----------
  function card(a) {
    const thumb = el("div", { class: "thumb" }, image(a), badge(primaryCategory(a)), isNew(a) ? el("span", { class: "new", text: "Nuovo" }) : null);
    const body = el("div", { class: "card-body" },
      el("h2", { text: a.title }),
      el("p", { class: "meta muted", text: `${a.source} · ${relativeDate(a.date)}` }));
    return el("a", { class: "card", href: `#${a.id}` }, thumb, body);
  }

  function renderGrid() {
    const list = visible();
    grid.replaceChildren(...list.slice(0, state.shown).map(card));
    $("empty").hidden = list.length > 0;
    moreBtn.hidden = list.length <= state.shown;
    $("count").textContent = list.length ? `${list.length} articoli` : "";
  }

  // ---------- dettaglio ----------
  function openArticle(a) {
    const cover = $("d-cover");
    cover.replaceChildren(image(a));
    const tags = [...a.categories.map(badge)];
    if (a.is_norm) tags.push(badge("normativa"));
    $("d-tags").replaceChildren(...tags);
    $("d-title").textContent = a.title;
    $("d-meta").textContent = `${a.source} · ${dateFmt.format(new Date(a.date))}`;
    $("d-summary").replaceChildren(...a.summary.map((s) => el("li", { text: s })));
    const note = $("d-note");
    note.hidden = !a.translated;
    note.textContent = a.translated ? `Tradotto automaticamente dall’inglese. Titolo originale: ${a.title_original}` : "";
    $("d-refs-box").hidden = a.refs.length === 0;
    $("d-refs").replaceChildren(...a.refs.map((r) => el("span", { text: r })));
    const link = $("d-link");
    link.href = a.url;
    link.textContent = `Leggi l’articolo completo su ${a.source} →`;
    if (!dialog.open) dialog.showModal();
    dialog.querySelector(".sheet").scrollTop = 0;
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

  $("updated").textContent = data.updated
    ? `Ultimo aggiornamento: ${dateTimeFmt.format(new Date(data.updated))}`
    : "Nessun dato ancora disponibile";
  renderFilters();
  renderGrid();
  syncFromHash();
})();
