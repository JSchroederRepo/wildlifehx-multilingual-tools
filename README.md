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
