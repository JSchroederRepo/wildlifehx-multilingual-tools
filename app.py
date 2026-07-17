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
import csv, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

TRIPTAXON_URL = "https://ebird.org/tripreport-internal/v1/taxon-list/{id}"
TRIPNARRATIVE_URL = "https://ebird.org/tripreport-internal/v1/narrative/{id}"
TRIPNUMSPECIES_URL = "https://ebird.org/tripreport-internal/v1/num-species/{id}"
TRIPNUMCHECKLISTS_URL = "https://ebird.org/tripreport-internal/v1/num-checklists/{id}"
TRIPLOCATIONS_URL = "https://ebird.org/tripreport-internal/v1/locations/{id}"
TAXONOMY_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird?locale={locale}"

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "ebird_tripreport_names")
CACHE_TTL_SECONDS = 30 * 24 * 3600

NAME_COLUMNS = [
    ("de", "german_name", "German", False),
    ("fr", "french_name", "French", False),
    ("es", "spanish_name", "Spanish", False),
    ("nl", "dutch_name", "Dutch", False),
    ("no", "norwegian_name", "Norwegian", False),
    ("zh_SIM", "chinese_name", "Chinese", True),
]
COLUMNS = ["scientific_name", "english_name"] + [c[1] for c in NAME_COLUMNS]


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
                "common_name": (row.get("COMMON_NAME") or "").strip(),
                "order": (row.get("ORDER") or "").strip(),
                "family_com": (row.get("FAMILY_COM_NAME") or "").strip(),
                "family_sci": (row.get("FAMILY_SCI_NAME") or "").strip(),
            }
    return name_map


def build_name_maps(force_refresh=False):
    return {locale: load_taxonomy(locale, force_refresh=force_refresh)
            for locale, _, _, _ in NAME_COLUMNS}


def build_table(trip_id, force_refresh=False):
    meta = get_trip_meta(trip_id)
    taxa = get_trip_taxa(trip_id)
    maps = build_name_maps(force_refresh=force_refresh)
    rows = []
    for taxon in taxa:
        code = taxon.get("speciesCode", "")
        row = {"scientific_name": taxon.get("sciName", ""),
               "english_name": taxon.get("commonName", ""), "species_code": code}
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
        if path in ("", "/", "/index.html"):
            try:
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, b"index.html not found", "text/plain; charset=utf-8")
        if path.rstrip("/").endswith("/api") or path == "/api":
            qs = urllib.parse.parse_qs(parsed.query)
            trip = (qs.get("trip", [""])[0]).strip()
            if not trip:
                return self._send(400, b"missing 'trip' parameter", "text/plain; charset=utf-8")
            try:
                trip_id = parse_trip_id(trip)
                meta, rows = build_table(trip_id)
                payload = json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False).encode("utf-8")
                return self._send(200, payload, "application/json; charset=utf-8")
            except ValueError as e:
                return self._send(400, str(e).encode("utf-8"), "text/plain; charset=utf-8")
            except Exception as e:
                return self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")
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
