#!/usr/bin/env python3
"""Raccoglie notizie sugli impianti elettrici speciali e genera i dati per il sito.

Usa solo la libreria standard di Python (nessuna installazione di pacchetti).
Flusso: legge i feed -> filtra per parole chiave -> scarica le pagine nuove ->
estrae immagine e testo -> riassume -> salva site/data/articles.json e articles.js.
"""
import concurrent.futures as futures
import datetime as dt
import difflib
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.json"
DATA_DIR = ROOT / "site" / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
WORKERS = 8
NOW = dt.datetime.now(dt.timezone.utc)


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------- rete

def fetch(url, timeout=20, max_bytes=2_500_000, accept="*/*"):
    """Scarica un URL e restituisce (testo, url_finale)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept,
                                               "Accept-Language": "it,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes)
        charset = resp.headers.get_content_charset()
        final_url = resp.geturl()
    if not charset:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
        charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        return raw.decode(charset, errors="replace"), final_url
    except LookupError:
        return raw.decode("utf-8", errors="replace"), final_url


# --------------------------------------------------------------------------- testo

def clean_text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def compile_keyword(kw):
    """Le parole chiave sono prefissi senza distinzione maiuscole; 're:' indica una regex."""
    if kw.startswith("re:"):
        return re.compile(kw[3:], re.I)
    return re.compile(r"(?<!\w)" + re.escape(kw).replace(r"\ ", r"\s+"), re.I)


def compile_all(keywords):
    return [(kw, compile_keyword(kw)) for kw in keywords]


def clean_title(title, source):
    t = clean_text(title)
    m = re.search(r"\s+[\|\-–—]\s+([^\|\-–—]{2,40})$", t)
    if m and source:
        tail, src = m.group(1).lower(), source.lower()
        if tail in src or src in tail:
            t = t[:m.start()].rstrip()
    if len(t) > 120:
        cut = max(t.rfind(sep, 0, 120) for sep in (": ", " – ", " - ", ", "))
        if cut < 60:
            cut = t.rfind(" ", 0, 118)
        t = t[:cut].rstrip(" ,:–-") + "…"
    return t


def canonical_url(url):
    p = urllib.parse.urlsplit(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid", "ref", "mc_cid", "mc_eid")]
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path, urllib.parse.urlencode(q), ""))


def title_key(title):
    return re.sub(r"\W+", " ", title.lower()).strip()


# --------------------------------------------------------------------------- feed

def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def first_img(fragment):
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", fragment or "", re.I)
    return m.group(1) if m else ""


def bing_real_url(link):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)
    return q["url"][0] if q.get("url") else link


def parse_feed(xml_text, feed, is_bing=False):
    # il testo è già decodificato: si toglie la dichiarazione di codifica per non farla confliggere
    xml_text = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml_text.lstrip("﻿"))
    root = ET.fromstring(xml_text.strip().encode("utf-8"))
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        d = {"title": "", "link": "", "desc": "", "full": "", "date": None, "image": "", "source": feed["name"]}
        for c in el:
            tag, text = local(c.tag), (c.text or "")
            if tag == "title":
                d["title"] = text
            elif tag == "link":
                href = c.attrib.get("href")
                if href and c.attrib.get("rel", "alternate") == "alternate":
                    d["link"] = href
                elif text.strip() and not d["link"]:
                    d["link"] = text.strip()
            elif tag in ("description", "summary"):
                d["desc"] = d["desc"] or text
            elif tag in ("content", "thumbnail") and c.attrib.get("url"):  # media:content / media:thumbnail
                d["image"] = d["image"] or c.attrib["url"]
            elif tag in ("encoded", "content"):
                d["full"] = d["full"] or text
            elif tag in ("pubDate", "published", "updated", "date"):
                d["date"] = d["date"] or parse_date(text)
            elif tag == "enclosure" and c.attrib.get("type", "image").startswith("image"):
                d["image"] = d["image"] or c.attrib.get("url", "")
            elif tag == "image":
                url_el = next((x for x in c if local(x.tag) == "url"), None)
                d["image"] = d["image"] or (url_el.text.strip() if url_el is not None and url_el.text else "")
            elif tag == "Image" and text:
                d["image"] = d["image"] or text
            elif tag == "Source" and text:
                d["source"] = text.strip()
        if not d["image"]:
            d["image"] = first_img(d["full"]) or first_img(d["desc"])
        if is_bing:
            d["link"] = bing_real_url(d["link"])
        if d["title"] and d["link"]:
            d["lang"] = feed.get("lang", "it")
            d["trusted"] = bool(feed.get("trusted"))
            items.append(d)
    return items


def bing_feed(query):
    url = "https://www.bing.com/news/search?" + urllib.parse.urlencode(
        {"q": query["q"], "format": "rss", "setlang": "it" if query["lang"] == "it" else "en-US",
         "cc": "IT" if query["lang"] == "it" else "US"})
    return {"name": "Bing News: " + query["q"], "url": url, "lang": query["lang"]}


def load_source(feed, is_bing=False):
    try:
        text, _ = fetch(feed["url"], timeout=25, accept="application/rss+xml, application/xml, text/xml, */*")
        items = parse_feed(text, feed, is_bing)
        return feed["name"], items, None
    except Exception as e:  # una fonte che non risponde non deve bloccare le altre
        return feed["name"], [], f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- rilevanza

class Matcher:
    def __init__(self, cfg):
        self.cats = [(c["id"], c["label"], compile_all(c["keywords"])) for c in cfg["categories"]]
        self.norm = compile_all(cfg["norm_keywords"])
        self.exclude = compile_all(cfg["exclude_title_keywords"])

    def classify(self, title, text):
        """Restituisce (punteggio, categorie, normativa?). Titolo = 3 punti, testo = 1 punto per parola chiave."""
        score, cats = 0, []
        for cid, _label, kws in self.cats:
            cat_score = 0
            for _kw, rx in kws:
                if rx.search(title):
                    cat_score += 3
                elif rx.search(text):
                    cat_score += 1
            if cat_score:
                cats.append((cat_score, cid))
                score += cat_score
        cats.sort(reverse=True)
        cats = [c for i, c in enumerate(cats) if i == 0 or (i == 1 and c[0] >= 3)]  # al massimo 2 categorie
        haystack = f"{title} {text}"
        is_norm = any(rx.search(haystack) for _kw, rx in self.norm)
        return score, [c for _s, c in cats], is_norm

    def excluded(self, title):
        return any(rx.search(title) for _kw, rx in self.exclude)


REF_RE = re.compile(
    r"\b(?:(?:UNI|CEI|EN|ISO|IEC|CLC|TS|TR)(?:[ /]+(?:UNI|CEI|EN|ISO|IEC|TS|TR))*\s?\d{1,6}(?:[-–:.]\d{1,4})*"
    r"|D\.?\s?Lgs\.?\s?(?:n\.\s?)?\d{1,3}/\d{2,4}"
    r"|[Rr]egolamento(?: \(UE\))?\s?(?:n\.\s?)?\d{2,4}/\d{2,4}"
    r"|[Dd]irettiva(?: \(UE\))?\s?\d{2,4}/\d{2,4})")


def find_refs(text, limit=6):
    seen, out = set(), []
    for m in REF_RE.finditer(text):
        ref = re.sub(r"\s+", " ", m.group(0)).strip(" .-–:")
        key = re.sub(r":\s?(19|20)\d\d$", "", ref.lower()).replace(" ", "")  # "UNI 11988:2025" == "UNI11988"
        if key not in seen and not re.fullmatch(r"(en|iso|iec|cei|uni)(19|20)\d\d", key):  # niente anni
            seen.add(key)
            out.append(ref)
    return out[:limit]


# --------------------------------------------------------------------------- pagina articolo

class PageParser(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg", "button", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.skip = 0
        self.article_depth = 0
        self.in_p = False
        self.buf = []
        self.article_paras, self.all_paras = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta.setdefault(key.lower(), a["content"])
        elif tag in self.SKIP:
            self.skip += 1
        elif tag == "article":
            self.article_depth += 1
        elif tag == "p" and not self.skip:
            self.in_p, self.buf = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag == "article" and self.article_depth:
            self.article_depth -= 1
        elif tag == "p" and self.in_p:
            self.in_p = False
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if len(text) >= 60:
                self.all_paras.append(text)
                if self.article_depth:
                    self.article_paras.append(text)

    def handle_data(self, data):
        if self.in_p and not self.skip:
            self.buf.append(data)

    def paragraphs(self):
        paras = self.article_paras if sum(map(len, self.article_paras)) >= 400 else self.all_paras
        boiler = re.compile(r"cookie|newsletter|privacy policy|tutti i diritti|all rights reserved|iscriviti|"
                            r"accetta|subscribe|sign up|©|fonti preferite|leggi anche|leggi tutto|aggiungi .{0,30} su google",
                            re.I)
        return [p for p in paras if not boiler.search(p)]


def read_page(url):
    text, final_url = fetch(url, timeout=20, accept="text/html,application/xhtml+xml")
    parser = PageParser()
    parser.feed(text)
    image = parser.meta.get("og:image") or parser.meta.get("twitter:image") or ""
    if image:
        image = urllib.parse.urljoin(final_url, image)
    desc = parser.meta.get("og:description") or parser.meta.get("description") or ""
    return {"image": image, "desc": clean_text(desc), "paras": parser.paragraphs()}


# --------------------------------------------------------------------------- riassunto

STOP = set("""
il lo la i gli le un uno una di a da in con su per tra fra e ed o ma che chi cui non più come anche si è sono
essere stato stati stata state ha hanno hai ho questo questa questi queste quello quella quelli quelle del dello della dei
degli delle al allo alla ai agli alle dal dallo dalla dai dagli dalle nel nello nella nei negli nelle sul sullo sulla sui
sugli sulle ci ne se sua suo sue suoi loro nostro nostra tutto tutti tutte ogni già solo può possono dove quando
the a an of to in on for with and or but that this these those is are was were be been has have had it its as at by from
their they them not more also which who will can may their about into than then there
""".split())
ABBREV = ("art.", "artt.", "n.", "nn.", "d.lgs.", "d.m.", "d.p.r.", "ecc.", "es.", "cfr.", "ing.", "dott.", "prof.",
          "sig.", "pag.", "all.", "s.p.a.", "s.r.l.", "no.", "inc.", "ltd.", "vs.")
NEWS_SIGNAL = re.compile(r"\b(obbligo|obblighi|entro il|dal \d|a partire dal|in vigore|pubblicat|approvat|aggiornament|"
                         r"novit|nuov[ao]|modific|abroga|scadenza|sanzion|must|required|will|new|effective|deadline|"
                         r"published|updated|amend)", re.I)


def tokens(s):
    return [w for w in re.findall(r"[a-zàèéìòù0-9]{3,}", s.lower()) if w not in STOP]


def split_sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Ý\"“«‘])", text)
    out = []
    for p in parts:
        if out and out[-1].lower().endswith(ABBREV):
            out[-1] += " " + p
        else:
            out.append(p)
    return [s.strip() for s in out if s.strip()]


def summarize(title, paragraphs, max_sentences=4, max_chars=850):
    sentences = [s for s in split_sentences(" ".join(paragraphs)) if 40 <= len(s) <= 420]
    if len(sentences) <= max_sentences:
        return sentences
    freq = Counter(t for s in sentences for t in set(tokens(s)))
    top = max(freq.values())
    title_words = set(tokens(title))
    scored = []
    for i, s in enumerate(sentences):
        toks = tokens(s)
        if not toks:
            continue
        score = sum(freq[t] for t in set(toks)) / (len(set(toks)) * top)
        score += 0.6 * len(title_words & set(toks)) / max(len(title_words), 1)
        score += 0.35 if NEWS_SIGNAL.search(s) else 0
        score += 0.25 if REF_RE.search(s) else 0
        score += 0.4 if i == 0 else (0.15 if i < 3 else 0)
        scored.append((score, i))
    chosen = sorted(i for _s, i in sorted(scored, reverse=True)[:max_sentences])
    result, total = [], 0
    for i in chosen:
        if total + len(sentences[i]) > max_chars and result:
            break
        result.append(sentences[i])
        total += len(sentences[i])
    return result


# --------------------------------------------------------------------------- traduzione

def translate_it(text):
    """Traduzione gratuita EN->IT tramite l'endpoint pubblico di Google Translate. Restituisce None se fallisce."""
    try:
        data = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": "it", "dt": "t", "q": text}).encode()
        req = urllib.request.Request("https://translate.googleapis.com/translate_a/single", data=data,
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return "".join(chunk[0] for chunk in payload[0] if chunk and chunk[0])
    except Exception:
        return None


def translate_article(title, summary):
    joined = translate_it("\n".join([title] + summary))
    if not joined:
        return title, summary, False
    lines = [ln.strip() for ln in joined.split("\n") if ln.strip()]
    if len(lines) == len(summary) + 1:
        return lines[0], lines[1:], True
    return lines[0], [" ".join(lines[1:])] if len(lines) > 1 else summary, True


# --------------------------------------------------------------------------- elaborazione

def make_article(entry, matcher, cfg):
    """Scarica la pagina e costruisce l'articolo pronto per il sito."""
    url = canonical_url(entry["link"])
    page = {"image": "", "desc": "", "paras": []}
    try:
        page = read_page(url)
    except Exception as e:
        log(f"  ! pagina non leggibile ({type(e).__name__}) {url}")

    body = page["paras"]
    if not body:  # pagina bloccata o senza testo: si ripiega sulla descrizione del feed
        fallback = clean_text(entry["full"] or entry["desc"]) or page["desc"]
        body = [fallback] if fallback else []
    summary = summarize(entry["title"], body)
    if not summary and body:
        summary = split_sentences(body[0])[:2] or [body[0][:300]]
    if not summary and page["desc"]:
        summary = [page["desc"][:400]]

    title = clean_title(entry["title"], entry["source"])
    translated = False
    if entry["lang"] != "it" and cfg["settings"].get("translate_english"):
        title, summary, translated = translate_article(title, summary)

    haystack = " ".join([entry["title"], clean_text(entry["desc"]), " ".join(body)[:6000]])
    image = page["image"] or entry["image"]
    if image.startswith("http://"):
        image = "https://" + image[len("http://"):]
    _score, categories, is_norm = matcher.classify(entry["title"], clean_text(entry["desc"]))
    return {
        "id": hashlib.sha1(url.encode()).hexdigest()[:12],
        "title": title,
        "title_original": clean_text(entry["title"]),
        "url": url,
        "source": entry["source"],
        "date": entry["date"].isoformat(),
        "added": NOW.isoformat(),
        "image": image,
        "summary": summary,
        "refs": find_refs(haystack),
        "categories": categories,
        "is_norm": is_norm,
        "lang": entry["lang"],
        "translated": translated,
    }


def load_existing():
    path = DATA_DIR / "articles.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("articles", [])
        except (ValueError, OSError):
            log("! articles.json illeggibile, riparto da zero")
    return []


def save(articles):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"updated": NOW.isoformat(), "articles": articles}
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    (DATA_DIR / "articles.json").write_text(text, encoding="utf-8")
    (DATA_DIR / "articles.js").write_text("window.NEWS_DATA = " + text + ";\n", encoding="utf-8")


def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = cfg["settings"]
    matcher = Matcher(cfg)

    existing = load_existing()
    known_urls = {a["url"] for a in existing}
    known_titles = [title_key(a["title_original"]) for a in existing][-400:]

    # 1) lettura di tutte le fonti in parallelo
    jobs = [(f, False) for f in cfg["feeds"]] + [(bing_feed(q), True) for q in cfg["bing_queries"]]
    entries, ok = [], 0
    with futures.ThreadPoolExecutor(WORKERS) as pool:
        for name, items, err in pool.map(lambda j: load_source(*j), jobs):
            if err:
                log(f"✗ {name}: {err}")
            else:
                ok += 1
                log(f"✓ {name}: {len(items)} voci")
                entries.extend(items)
    if not ok:
        log("Nessuna fonte raggiungibile.")
        return 1

    # 2) filtro: data, duplicati, rilevanza
    oldest = NOW - dt.timedelta(days=settings["max_age_days"])
    candidates, seen_urls, seen_titles = [], set(known_urls), list(known_titles)
    for e in sorted(entries, key=lambda x: x["date"] or NOW, reverse=True):
        e["date"] = min(e["date"] or NOW, NOW)
        url = canonical_url(e["link"])
        tkey = title_key(e["title"])
        if e["date"] < oldest or url in seen_urls:
            continue
        if any(difflib.SequenceMatcher(None, tkey, k).ratio() > 0.88 for k in seen_titles):
            continue
        desc = clean_text(e["desc"])
        score, _cats, _norm = matcher.classify(e["title"], desc)
        min_score = 1 if e["trusted"] else settings["min_score"]
        if score < min_score or (not e["trusted"] and matcher.excluded(e["title"])):
            continue
        seen_urls.add(url)
        seen_titles.append(tkey)
        candidates.append(e)
    candidates = candidates[:settings["max_new_per_run"]]
    log(f"\nNuovi articoli pertinenti: {len(candidates)}")

    # 3) pagina, riassunto e traduzione dei soli articoli nuovi
    with futures.ThreadPoolExecutor(WORKERS) as pool:
        new_articles = list(pool.map(lambda e: make_article(e, matcher, cfg), candidates))
    for a in new_articles:
        log(f"  + [{', '.join(a['categories']) or '-'}] {a['title']}  ({a['source']})")

    # 4) unione con l'archivio, pulizia e salvataggio
    keep_from = NOW - dt.timedelta(days=settings["keep_days"])
    merged = [a for a in existing + new_articles if dt.datetime.fromisoformat(a["date"]) >= keep_from]
    merged.sort(key=lambda a: a["date"], reverse=True)
    save(merged[:settings["max_articles"]])
    log(f"Archivio: {len(merged[:settings['max_articles']])} articoli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
