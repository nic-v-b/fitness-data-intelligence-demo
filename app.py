"""Serve the local activity explorer or export its synthetic demonstration data."""

import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from analysis_core import AXES, SIGNALS
from athlete import athlete_demo
from comparative import build_comparative
from portfolio import public_portfolio
from synthetic_data import build_dataset


STATIC = Path(__file__).resolve().parent / "web"
LEAFLET = STATIC.parent / "node_modules" / "leaflet" / "dist"
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/comparative.js": ("comparative.js", "text/javascript; charset=utf-8"),
    "/portfolio.js": ("portfolio.js", "text/javascript; charset=utf-8"),
    "/route-map.js": ("route-map.js", "text/javascript; charset=utf-8"),
    "/athlete.js": ("athlete.js", "text/javascript; charset=utf-8"),
    "/favicon.png": ("favicon.png", "image/png"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def sample_csv(metadata, activity):
    output = io.StringIO(newline="")
    provenance = {
        "dataset_id": metadata["dataset_id"], "dataset_type": metadata["dataset_type"],
        "schema_version": metadata["schema_version"], "processing_version": metadata["processing_version"],
        "activity_id": activity["id"], "sport": activity["sport"],
        "coordinate_system": metadata["coordinate_system"],
        "generation_json": json_bytes(metadata["generation"]).decode().rstrip("\n"),
        "units_json": json_bytes(metadata["units"]).decode().rstrip("\n"),
        "assumptions_json": json_bytes(metadata["assumptions"]).decode().rstrip("\n"),
    }
    fields = ["sample_index", *AXES, *SIGNALS, "speed_kmh", "pace_s_per_km",
              *(f"{name}_quality" for name in SIGNALS), *provenance]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in activity["samples"]:
        writer.writerow({"sample_index": record["index"], **record["source"], **record["derived"],
                         **{f"{name}_quality": record["quality"][name] for name in SIGNALS},
                         **provenance})
    return output.getvalue().encode("utf-8")


def export_files(dataset):
    if dataset["metadata"]["dataset_type"] != "synthetic":
        raise ValueError("Only the synthetic dataset can be exported")
    return {"ridge-traverse.json": json_bytes(dataset),
            **{f"{run['id']}.csv": sample_csv(dataset["metadata"], run) for run in dataset["activities"]}}


def mapbox_options(token_path, logo_path):
    from private_preview import PRIVATE_ROOT

    if not token_path and not logo_path:
        return None
    if not token_path or not logo_path:
        raise ValueError("Mapbox requires a public token file and the official attribution logo")
    token_path, logo_path = token_path.resolve(), logo_path.resolve()
    if (not token_path.is_relative_to(PRIVATE_ROOT) or not logo_path.is_relative_to(PRIVATE_ROOT)
            or logo_path.suffix.lower() not in (".svg", ".png")):
        raise ValueError("Use an ignored private-data token file and an official Mapbox SVG or PNG logo")
    try:
        token = token_path.read_text(encoding="utf-8-sig").strip()
        logo = logo_path.read_bytes()
    except OSError:
        raise ValueError("Could not read the local Mapbox attribution assets") from None
    if not re.fullmatch(r"pk\.[A-Za-z0-9._-]+", token) or not logo:
        raise ValueError("Mapbox expects a public pk. token and a nonempty attribution logo")
    return token, logo, {".svg": "image/svg+xml", ".png": "image/png"}[logo_path.suffix.lower()]


def create_server(port, dataset, comparative=None, *, portfolio=None, mapbox=None):
    dataset_type = dataset["metadata"]["dataset_type"]
    synthetic = dataset_type == "synthetic"
    responses = {path: ((STATIC / name).read_bytes(), media_type, None)
                 for path, (name, media_type) in STATIC_ROUTES.items()}
    responses["/api/dataset"] = (json_bytes(dataset), "application/json; charset=utf-8", None)
    if synthetic:
        comparative = build_comparative(dataset["activities"], synthetic=True)
        portfolio = public_portfolio(dataset)
        mapbox = None
        for filename, content in export_files(dataset).items():
            media_type = "text/csv" if filename.endswith(".csv") else "application/json"
            responses[f"/exports/{filename}"] = (content, f"{media_type}; charset=utf-8", filename)
    if comparative is not None:
        responses["/api/comparative"] = (json_bytes(comparative), "application/json; charset=utf-8", None)
    leaflet = not synthetic and all((LEAFLET / path).is_file() for path in ("leaflet.js", "leaflet.css"))
    if leaflet:
        responses["/leaflet.js"] = ((LEAFLET / "leaflet.js").read_bytes(), "text/javascript; charset=utf-8", None)
        responses["/leaflet.css"] = ((LEAFLET / "leaflet.css").read_bytes(), "text/css; charset=utf-8", None)
    tile_access = bool(leaflet and mapbox)
    if tile_access:
        responses["/mapbox-logo"] = (mapbox[1], mapbox[2], None)
    if portfolio is not None:
        options = {"leaflet": bool(leaflet), "satellite": mapbox[0] if tile_access else None}
        responses["/api/portfolio"] = (json_bytes({**portfolio.index(), "map": options}),
                                       "application/json; charset=utf-8", None)
        responses["/api/athlete"] = (json_bytes(athlete_demo()), "application/json; charset=utf-8", None)
        responses["/api/athlete/compressed"] = (json_bytes(athlete_demo("compressed")), "application/json; charset=utf-8", None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            if synthetic:
                super().log_message(format, *args)

        def do_GET(self):
            self.respond(include_body=True)

        def do_HEAD(self):
            self.respond(include_body=False)

        def respond(self, include_body):
            if not synthetic and (self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                            or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            response = responses.get(path)
            if response is None and portfolio is not None and path.startswith("/api/activities/"):
                key = path.removeprefix("/api/activities/")
                if key in portfolio.activities:
                    response = json_bytes(portfolio.detail(key)), "application/json; charset=utf-8", None
                else:
                    activity_id, separator, peer_id = key.partition("/compare/")
                    if separator and (pair := portfolio.compare_runs(activity_id, peer_id)) is not None:
                        response = json_bytes(pair), "application/json; charset=utf-8", None
            if response is None:
                self.send_error(404)
                return
            content, media_type, filename = response
            self.send_response(200)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            csp = "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            if tile_access:
                csp += "; img-src 'self' data: https://api.mapbox.com"
            self.send_header("Content-Security-Policy", csp)
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Referrer-Policy", "no-referrer")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            if include_body:
                self.wfile.write(content)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="run the local browser application (default)")
    serve.add_argument("--port", type=int, default=8000)
    export = commands.add_parser("export", help="write reproducible demonstration files")
    export.add_argument("--output", type=Path, default=Path("artifacts/exports"))
    args = parser.parse_args()
    dataset = build_dataset()
    if args.command == "export":
        args.output.mkdir(parents=True, exist_ok=True)
        for filename, content in export_files(dataset).items():
            (args.output / filename).write_bytes(content)
        print(f"Wrote demonstration exports to {args.output}")
        return
    with create_server(getattr(args, "port", 8000), dataset) as server:
        print(f"Fitness Data Intelligence is available at http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
