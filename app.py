#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WildlifeHX combined backend: eBird Trip Report -> multilingual species table.

Serves /api?trip=<url-or-id>  (eBird data + multilingual names, server-side because
ebird.org sends no CORS headers) and, for local use, serves index.html at /.

In production (pplx.app) the static index.html is served from S3 and only
/port/8000/api requests are proxied to this server. Stdlib-only, no dependencies.
"""
from __future__ import annotations
import csv, io, json, mimetypes, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

TRIPTAXON_URL = "https://ebird.org/tripreport-internal/v1/taxon-list/{id}"
TRIPNARRATIVE_URL = "https://ebird.org/tripreport-internal/v1/narrative/{id}"
TRIPNUMSPECIES_URL = "https://ebird.org/tripreport-internal/v1/num-species/{id}"
TRIPNUMCHECKLISTS_URL = "https://ebird.org/tripreport-internal/v1/num-checklists/{id}"
TRIPLOCATIONS_URL = "https://ebird.org/tripreport-internal/v1/locations/{id}"
TRIPCHECKLISTS_URL = "https://ebird.org/tripreport-internal/v1/checklists/{id}"
TRIPTAXONDETAIL_URL = "https://ebird.org/tripreport-internal/v1/taxon-detail/{id}/{code}"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird?locale={locale}"

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "ebird_tripreport_names")
CACHE_TTL_SECONDS = 30 * 24 * 3600

NAME_COLUMNS = [
    ("de", "german_name", "German", False),
    ("fr", "french_name", "French", False),
    ("es", "spanish_name", "Spanish", False),
    ("nl", "dutch_name", "Dutch", False),
    ("no", "norwegian_name", "Norwegian", False),
    ("da", "danish_name", "Danish", False),
    ("sv", "swedish_name", "Swedish", False),
    ("fi", "finnish_name", "Finnish", False),
    ("pl", "polish_name", "Polish", False),
    ("ru", "russian_name", "Russian", False),
    ("zh_SIM", "chinese_name", "Chinese", True),
]
COLUMNS = ["scientific_name", "english_name"] + [c[1] for c in NAME_COLUMNS]

# Locales served to the translator for bird names. These are Cornell/eBird
# taxonomy common-name sets — the same namesets Birds of the World uses.
BIRD_NAME_LOCALES = ["en", "de", "fr", "es", "nl", "no", "da", "sv", "fi", "pl", "ru", "zh_SIM", "ja"]


def http_get(url, accept="application/json", timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", "replace")[:200]
        except Exception: pass
        raise RuntimeError(f"HTTP {e.code} for {url}\n{body}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching {url}: {e.reason}") from None


def http_get_json(url):
    raw = http_get(url, accept="application/json")
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Could not parse JSON from {url}: {e}\n{text[:200]}") from None


def has_cjk(s):
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def parse_trip_id(url_or_id):
    s = str(url_or_id).strip()
    if s.isdigit():
        return s
    m = re.search(r"tripreport/(\d+)", s)
    if m:
        return m.group(1)
    for part in reversed(urllib.parse.urlparse(s).path.split("/")):
        if part.isdigit():
            return part
    m = re.search(r"(\d{4,})", s)
    if m:
        return m.group(1)
    raise ValueError(f"Could not find a trip-report id in: {url_or_id!r}")


def get_trip_taxa(trip_id):
    data = http_get_json(TRIPTAXON_URL.format(id=trip_id))
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected taxon-list response for {trip_id}")
    return data


def get_trip_meta(trip_id):
    meta = {"trip_id": trip_id}
    try:
        ns = http_get_json(TRIPNUMSPECIES_URL.format(id=trip_id))
        if isinstance(ns, list) and len(ns) >= 1: meta["num_species"] = ns[0]
        if isinstance(ns, list) and len(ns) >= 2: meta["num_other_taxa"] = ns[1]
    except Exception: pass
    try:
        nc = http_get_json(TRIPNUMCHECKLISTS_URL.format(id=trip_id))
        if isinstance(nc, int): meta["num_checklists"] = nc
    except Exception: pass
    try:
        nar = http_get_json(TRIPNARRATIVE_URL.format(id=trip_id))
        if isinstance(nar, dict): meta["narrative"] = nar.get("narrative", "")
    except Exception: pass
    try:
        locs = http_get_json(TRIPLOCATIONS_URL.format(id=trip_id))
        if isinstance(locs, list):
            countries = []
            for loc in locs:
                c = loc.get("countryName") or loc.get("countryCode")
                if c and c not in countries: countries.append(c)
            meta["countries"] = countries
            meta["num_locations"] = len(locs)
    except Exception: pass
    return meta


def get_trip_checklists(trip_id):
    data = http_get_json(TRIPCHECKLISTS_URL.format(id=trip_id))
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected checklists response for {trip_id}")
    return data


def get_taxon_detail(trip_id, code):
    try:
        data = http_get_json(TRIPTAXONDETAIL_URL.format(id=trip_id, code=code))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"checklists": []}


def _cache_path(locale):
    return os.path.join(CACHE_DIR, f"ebird_taxonomy_{locale}.csv")


def load_taxonomy(locale, force_refresh=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(locale)
    use_cache = False
    if not force_refresh and os.path.exists(path):
        if time.time() - os.path.getmtime(path) < CACHE_TTL_SECONDS:
            use_cache = True
    if not use_cache:
        raw = http_get(TAXONOMY_URL.format(locale=locale), accept="text/csv", timeout=120)
        with open(path, "wb") as f: f.write(raw)
    name_map = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("SPECIES_CODE") or "").strip()
            if not code: continue
            name_map[code] = {
                "sci_name": (row.get("SCIENTIFIC_NAME") or "").strip(),
                "common_name": (row.get("COMMON_NAME") or "").strip(),
                "order": (row.get("ORDER") or "").strip(),
                "family_com": (row.get("FAMILY_COM_NAME") or "").strip(),
                "family_sci": (row.get("FAMILY_SCI_NAME") or "").strip(),
            }
    return name_map


def build_name_maps(force_refresh=False):
    return {locale: load_taxonomy(locale, force_refresh=force_refresh)
            for locale, _, _, _ in NAME_COLUMNS}


# ---- in-memory cache + bird-name lookup (translator, Birds-of-the-World-aligned) ----
_TAX_CACHE = {}
_SCI_INDEX = None


def get_taxonomy(locale):
    m = _TAX_CACHE.get(locale)
    if m is None:
        m = load_taxonomy(locale)
        _TAX_CACHE[locale] = m
    return m


def _norm_sci(s):
    s = " ".join(str(s or "").strip().lower().split())
    return s.replace("\u00d7", "x").replace(" x ", " ")


def get_bird_names(sci_name):
    """Return Cornell/eBird taxonomy common names for a bird, keyed by locale."""
    global _SCI_INDEX
    en = get_taxonomy("en")
    if _SCI_INDEX is None:
        _SCI_INDEX = {}
        for code, info in en.items():
            key = _norm_sci(info.get("sci_name", ""))
            if key:
                _SCI_INDEX.setdefault(key, code)
    code = _SCI_INDEX.get(_norm_sci(sci_name))
    if not code:
        return {"found": False}
    names = {}
    for loc in BIRD_NAME_LOCALES:
        names[loc] = get_taxonomy(loc).get(code, {}).get("common_name", "")
    return {"found": True, "scientific": sci_name, "speciesCode": code,
            "english": names.get("en", ""), "names": names}


def build_table(trip_id, force_refresh=False):
    meta = get_trip_meta(trip_id)
    taxa = get_trip_taxa(trip_id)
    maps = build_name_maps(force_refresh=force_refresh)
    rows = []
    for taxon in taxa:
        code = taxon.get("speciesCode", "")
        row = {"scientific_name": taxon.get("sciName", ""),
               "english_name": taxon.get("commonName", ""), "species_code": code,
               "obs_count": int(taxon.get("numIndividuals") or 0)}
        for locale, col_key, _, _ in NAME_COLUMNS:
            info = maps[locale].get(code, {})
            name = info.get("common_name", "")
            row[col_key] = name
            if locale == "zh_SIM":
                row["chinese_is_fallback"] = bool(name) and not has_cjk(name)
        rows.append(row)
    meta["chinese_native_count"] = sum(1 for r in rows if not r.get("chinese_is_fallback"))
    meta["chinese_fallback_count"] = sum(1 for r in rows if r.get("chinese_is_fallback"))
    return meta, rows


def build_table_for_date(trip_id, date_str, force_refresh=False):
    """Species (and checklists) recorded on one specific day within a trip report.

    eBird's per-trip taxon-list only gives trip-wide totals, so to isolate a single
    day we cross-reference each species' taxon-detail (which lists the individual
    checklists it was seen on, with dates) against the trip's checklist list.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    checklists = get_trip_checklists(trip_id)
    matching_checklists = [c for c in checklists
                            if str(c.get("isoObsDate", "")).startswith(date_str)]

    taxa = get_trip_taxa(trip_id)
    maps = build_name_maps(force_refresh=force_refresh)
    rows = []

    if matching_checklists:
        def fetch_detail(taxon):
            code = taxon.get("speciesCode", "")
            detail = get_taxon_detail(trip_id, code)
            day_cls = [c for c in (detail.get("checklists") or [])
                       if str(c.get("obsDt", "")).startswith(date_str)]
            return taxon, code, day_cls

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(fetch_detail, t) for t in taxa]
            for fut in as_completed(futures):
                taxon, code, day_cls = fut.result()
                if not day_cls or not code:
                    continue
                obs_count = sum(int(c.get("howMany") or 0) for c in day_cls)
                row = {"scientific_name": taxon.get("sciName", ""),
                       "english_name": taxon.get("commonName", ""), "species_code": code,
                       "obs_count": obs_count}
                for locale, col_key, _, _ in NAME_COLUMNS:
                    info = maps[locale].get(code, {})
                    name = info.get("common_name", "")
                    row[col_key] = name
                    if locale == "zh_SIM":
                        row["chinese_is_fallback"] = bool(name) and not has_cjk(name)
                rows.append(row)
    rows.sort(key=lambda r: r.get("scientific_name", ""))

    countries, locations, seen_loc = [], [], set()
    for c in matching_checklists:
        loc = c.get("loc") or {}
        cn = loc.get("countryName") or loc.get("countryCode")
        if cn and cn not in countries:
            countries.append(cn)
        lid = loc.get("locId") or loc.get("locID")
        if lid and lid not in seen_loc:
            seen_loc.add(lid)
            locations.append(loc.get("name") or "")

    meta = {"trip_id": trip_id, "date": date_str,
            "num_checklists": len(matching_checklists), "num_species": len(rows),
            "num_locations": len(locations), "countries": countries}
    meta["chinese_native_count"] = sum(1 for r in rows if not r.get("chinese_is_fallback"))
    meta["chinese_fallback_count"] = sum(1 for r in rows if r.get("chinese_is_fallback"))

    checklists_out = []
    for c in matching_checklists:
        loc = c.get("loc") or {}
        checklists_out.append({
            "subId": c.get("subId") or c.get("subID"),
            "obsDt": c.get("obsDt"), "obsTime": c.get("obsTime"),
            "isoObsDate": c.get("isoObsDate"), "numSpecies": c.get("numSpecies"),
            "locName": loc.get("name") or "",
        })
    checklists_out.sort(key=lambda c: c.get("isoObsDate") or "")
    return meta, rows, checklists_out


HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        # serve the combined UI locally (production serves index.html from S3)
        if path in ("", "/"):
            path = "/index.html"
        if path.rstrip("/").endswith("/api") or path == "/api":
            qs = urllib.parse.parse_qs(parsed.query)
            bird = (qs.get("birdnames", [""])[0]).strip()
            if bird:
                try:
                    res = get_bird_names(bird)
                    return self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"),
                                      "application/json; charset=utf-8")
                except Exception as e:
                    return self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")
            trip = (qs.get("trip", [""])[0]).strip()
            if not trip:
                return self._send(400, b"missing 'trip' parameter", "text/plain; charset=utf-8")
            date = (qs.get("date", [""])[0]).strip()
            if date and not DATE_RE.match(date):
                return self._send(400, b"'date' must be in YYYY-MM-DD format",
                                  "text/plain; charset=utf-8")
            try:
                trip_id = parse_trip_id(trip)
                if date:
                    meta, rows, checklists = build_table_for_date(trip_id, date)
                    payload = json.dumps({"meta": meta, "rows": rows, "checklists": checklists},
                                         ensure_ascii=False).encode("utf-8")
                else:
                    meta, rows = build_table(trip_id)
                    payload = json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False).encode("utf-8")
                return self._send(200, payload, "application/json; charset=utf-8")
            except ValueError as e:
                return self._send(400, str(e).encode("utf-8"), "text/plain; charset=utf-8")
            except Exception as e:
                return self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")
        # Static file serving: pages (index/ebird/inaturalist/birdid), styles.css,
        # shared.js, and the images/ and downloads/ folders. Needed for standalone
        # self-hosting (e.g. Render) where this process is the only server.
        rel = urllib.parse.unquote(path).lstrip("/")
        full = os.path.normpath(os.path.join(HERE, rel))
        if full == HERE or full.startswith(HERE + os.sep):
            if os.path.isfile(full):
                ctype, _ = mimetypes.guess_type(full)
                ctype = ctype or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                    ctype += "; charset=utf-8"
                try:
                    with open(full, "rb") as f:
                        return self._send(200, f.read(), ctype)
                except OSError:
                    pass
        self._send(404, b"not found", "text/plain; charset=utf-8")


def run_server(port):
    os.makedirs(CACHE_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    port = 8000
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        port = int(sys.argv[i + 1])
    run_server(port)
