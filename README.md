# WildlifeHX Multilingual Species Tools

Two expedition-lecturer tools in one app for building multilingual species lists
from **eBird trip reports** and **iNaturalist projects**. Designed for polar/nature
expedition cruises: pick the taxa you care about, tick them on/off, and get names in
English plus optional German, French, Spanish, Norwegian, Dutch, and Chinese.

- **eBird Trip Report** — paste a trip-report URL/ID; get the trip's species with
  multilingual common names. Needs the small Python backend (`app.py`) because
  ebird.org does not allow direct browser requests.
- **iNaturalist Project** — paste a project URL/slug/ID; get species counts grouped
  into Plants, Birds, Vertebrates, Insects, Plankton, and Other, with multilingual
  vernacular names. Runs fully in the browser (calls the public iNaturalist API).

No JavaScript libraries, no Python packages — the backend is Python 3 standard
library only.

## Run locally

```bash
python3 app.py --serve --port 8000
```

Then open <http://localhost:8000>. Both tools work; the eBird tab talks to the
backend on the same origin (`/api`), the iNaturalist tab talks directly to
`api.inaturalist.org`.

> Python 3.7+ is the only requirement. No `pip install` needed.

## Host it publicly (standalone, outside Perplexity)

Because `app.py` serves both the page and `/api` on one origin, the same command
works on any host that runs Python:

- **Render / Railway / Fly.io / a VPS** — run `python3 app.py --serve --port $PORT`
  and expose the port. This makes both tools work publicly.
- **Vercel** — wrap the `/api` handler as a Python serverless function and serve
  `index.html` statically.

### iNaturalist-only on a static host (GitHub Pages, Netlify)

The iNaturalist tab is pure client-side, so `index.html` alone works on any static
host — you can drop it on GitHub Pages with no backend. The eBird tab requires the
backend, so it will not function on a static-only host.

## Data sources

This tool does not maintain its own species database — it fetches taxonomy and names
live from the eBird and iNaturalist APIs.

### eBird tab (fetched server-side by `app.py`)

ebird.org does not send CORS headers, so these calls are made from the Python
backend and proxied to the browser via `/api?trip=<id>`.

- **Trip report data** — eBird's internal trip-report API:
  - `https://ebird.org/tripreport-internal/v1/taxon-list/{id}` — the species/taxon
    list for the trip (also the source of the scientific name and the English name).
  - `…/narrative/{id}`, `…/num-species/{id}`, `…/num-checklists/{id}`,
    `…/locations/{id}` — trip metadata (description, counts, countries, locations).
- **Multilingual common names** — the eBird taxonomy, one CSV per locale:
  `https://api.ebird.org/v2/ref/taxonomy/ebird?locale={locale}`
  Locales fetched: `de` (German), `fr` (French), `es` (Spanish), `nl` (Dutch),
  `no` (Norwegian), `zh_SIM` (Simplified Chinese). Each locale's taxonomy is cached
  locally as a CSV under `~/.cache/ebird_tripreport_names/ebird_taxonomy_{locale}.csv`
  for ~30 days, then refreshed automatically.

### iNaturalist tab (fetched client-side, in the browser)

The iNaturalist API sends permissive CORS headers, so these calls go straight from
the browser to `https://api.inaturalist.org/v1` — no backend involved.

- **Project resolution** — `GET /v1/projects/{slug-or-id}` (falls back to
  `/v1/projects?q={input}` search if the input isn't a direct ID/slug).
- **Species counts** — `GET /v1/observations/species_counts?project_id={id}&page={n}&per_page=500`,
  paginated until all taxa are collected. Each taxon returns `name` (scientific),
  `rank`, `iconic_taxon_name`, `preferred_common_name` (English), `ancestor_ids`,
  and an observation `count`.
- **Vernacular (multilingual) names** — `GET /v1/taxa?id={comma-separated}&all_names=true&locale=en&per_page=200`,
  fetched in batches of 100 taxon IDs. Each taxon's `names[]` carries
  `{name, locale, place_id, is_valid}`.
- **Language → locale mapping** used to pick each name: German `de`; French `fr`;
  Spanish `es`; Dutch `nl`; Norwegian `nb` → `nn` → `no`; Chinese `zh-CN` → `zh-Hans`
  → `zh` (Traditional Chinese is shown as a greyed-out fallback when no Simplified
  name exists). English comes from the taxon's `preferred_common_name`.
- **Category classification** (Plants / Birds / Vertebrates / Insects / Plankton /
  Other) is computed locally in the browser from each taxon's `iconic_taxon_name`
  and `ancestor_ids`; the Plankton bucket matches ancestry against a curated set of
  marine zooplankton/phytoplankton taxon IDs (e.g. Copepoda, Euphausiacea, diatoms).

### Attribution

- eBird data © [Cornell Lab of Ornithology](https://ebird.org). This tool is
  independent and not affiliated with or endorsed by the Cornell Lab.
- iNaturalist data via the [iNaturalist API](https://api.inaturalist.org/v1);
  observations and photos are governed by iNaturalist's terms and the licenses chosen
  by each contributor.

## How the categories are assigned (iNaturalist)

Precedence: Birds (Aves) → Plants (Plantae) → Insects (Insecta) → Vertebrates
(Mammalia/Reptilia/Amphibia/Actinopterygii/Chondrichthyes) → Plankton (a curated set
of marine zooplankton/phytoplankton taxon IDs matched via ancestry) → Other.

## Language selection

For each locale the code prefers a valid, place-independent name; falls back to the
first valid name; then the first available. Chinese prefers Simplified (zh-CN), then
zh-Hans, then Traditional (zh, shown in grey). Norwegian covers `nb`, `nn`, `no`.

## Test inputs

- eBird trip report: `546161` (a Greenland voyage).
- iNaturalist project: `city-nature-challenge-2019-the-wasatch` (project id 28039).

## Notes

- eBird taxonomy is cached locally under `~/.cache/ebird_tripreport_names/` for
  ~30 days.
- All state is in-memory in the browser — nothing is stored server-side.

## License

MIT — free to use, share, and modify.
