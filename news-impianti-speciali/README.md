# Radar Impianti Speciali

Sito di notizie e novità normative su rivelazione incendi, EVAC, TVCC, antintrusione, cablaggio strutturato e BMS/BACS.
Si aggiorna da solo ogni 3 ore: raccoglie le notizie dal web, tiene solo quelle pertinenti, ne crea un riassunto
e le pubblica. Ogni scheda mostra copertina e titolo; al clic si apre il riassunto e, in fondo, il link all'articolo originale.

## Come funziona

```
config/sources.json        fonti (feed RSS + ricerche Bing News) e parole chiave per categoria
scripts/update_news.py     raccoglie, filtra, riassume (senza AI, senza costi) e salva i dati
site/                      il sito (HTML/CSS/JS) e i dati in site/data/
.github/workflows/         l'aggiornamento automatico ogni 3 ore, gratuito su GitHub
```

Il riassunto è "estrattivo": lo script sceglie le 3-4 frasi più significative dell'articolo, dando peso a novità,
obblighi, date e riferimenti normativi (UNI, CEI, EN, D.Lgs., direttive). Gli articoli in inglese vengono tradotti
automaticamente in italiano. I riferimenti normativi citati compaiono anche come etichette nella scheda.

## Pubblicazione (una volta sola, circa 10 minuti)

Il sito gira su GitHub Pages, gratuito, e si apre da qualsiasi PC o telefono con un link. Non serve installare nulla.

1. Crea un account gratuito su <https://github.com>.
2. In alto a destra: **+ → New repository**. Nome, ad esempio, `radar-impianti-speciali`. Scegli **Public** e crea.
3. Nella pagina del repository: **uploading an existing file**. Trascina **tutto il contenuto** di questa cartella
   (compresa la cartella `.github`) e conferma con **Commit changes**.
4. **Settings → Pages → Source: GitHub Actions**.
5. Scheda **Actions → "Aggiorna notizie e pubblica il sito" → Run workflow**.
6. Dopo circa un minuto l'indirizzo del sito compare in **Settings → Pages**
   (di solito `https://TUO-NOME.github.io/radar-impianti-speciali/`). Salvalo nei preferiti sul PC di casa e su quello dell'ufficio.

Da lì in poi l'aggiornamento è automatico.

## Personalizzare

Tutto si modifica in `config/sources.json` (direttamente dal sito di GitHub, con l'icona della matita):

- **Aggiungere una fonte**: nuova riga in `feeds` con nome, indirizzo del feed RSS e lingua (`it` o `en`).
  Con `"trusted": true` la fonte è considerata sempre pertinente al settore (basta una parola chiave).
- **Aggiungere una ricerca**: nuova riga in `bing_queries`. Funzionano meglio le ricerche brevi (es. `UNI 11224`).
- **Cambiare le parole chiave** di una categoria: lista `keywords`. Le voci che iniziano con `re:` sono espressioni regolari.
- **Scartare argomenti indesiderati**: `exclude_title_keywords` (vale per le fonti generaliste).
- **Essere più o meno severi**: `min_score` in `settings` (più alto = meno articoli, più pertinenti).

## Limiti da conoscere

- I riassunti sono automatici e non sostituiscono la lettura della norma o dell'articolo originale.
- Alcuni siti bloccano la lettura automatica: in quel caso il riassunto si basa sull'anteprima del feed.
- Le fonti che non hanno un feed RSS non sono raggiungibili (ad esempio EUR-Lex o il sito dei Vigili del Fuoco).
  Le loro novità arrivano comunque quando le riprendono le riviste di settore.
- Il sito è pubblico (necessario per GitHub Pages gratuito) ma contiene solo titoli, riassunti brevi e link alle fonti.
  Le ricerche Bing News sono concesse dal fornitore per uso personale e non commerciale.
