import csv
import io
import json
from math import hypot
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from analysis_core import interpolate
from app import create_server, export_files
from synthetic_data import build_dataset


class DatasetTests(unittest.TestCase):
    def test_exact_shared_geometry_on_the_declared_slice(self):
        dataset = build_dataset()
        self.assertEqual(dataset["metadata"]["dataset_type"], "synthetic")
        self.assertEqual(len(dataset["activities"]), 2)
        shared_routes, starts, finishes = [], [], []
        for run in dataset["activities"]:
            self.assertEqual(run["sport"], "running")
            start = run["shared_segment"]["start_index"]
            end = run["shared_segment"]["end_index"]
            coordinates = [(s["source"]["x_m"], s["source"]["y_m"]) for s in run["samples"]]
            shared_routes.append(coordinates[start:end + 1])
            starts.append(coordinates[0])
            finishes.append(coordinates[-1])
            self.assertAlmostEqual(run["summary"]["distance_m"], sum(
                hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
            ), places=5)
        self.assertEqual(len(shared_routes[0]), 127)
        self.assertEqual(shared_routes[0], shared_routes[1])
        self.assertNotEqual(starts[0], starts[1])
        self.assertNotEqual(finishes[0], finishes[1])

    def test_timeline_and_route_sample_contract(self):
        for run in build_dataset()["activities"]:
            for index, sample in enumerate(run["samples"]):
                source = sample["source"]
                self.assertEqual(sample["index"], index)
                same = interpolate(run["samples"], "elapsed_s", source["elapsed_s"])
                for field in ("elapsed_s", "distance_m", "x_m", "y_m"):
                    self.assertEqual(same[field], source[field])
                for field, status in sample["quality"].items():
                    self.assertEqual(same[field], source[field] if status == "valid" else None)
            self.assertEqual(run["summary"]["sample_count"], len(run["samples"]))
            self.assertEqual(run["samples"][-1]["source"]["elapsed_s"], run["summary"]["elapsed_s"])

    def test_generated_faults_remain_visible_in_the_contract(self):
        west, east = build_dataset()["activities"]
        self.assertEqual(west["summary"]["quality_counts"]["heart_rate_bpm"],
                         {"valid": 195, "missing": 3, "invalid": 1})
        self.assertEqual(east["summary"]["quality_counts"]["speed_mps"],
                         {"valid": 196, "missing": 2, "invalid": 1})
        self.assertEqual(west["samples"][112]["source"]["heart_rate_bpm"], 292)
        self.assertIsNone(west["samples"][59]["source"]["heart_rate_bpm"])
        self.assertIsNone(east["samples"][146]["derived"]["speed_kmh"])
        for run in (west, east):
            self.assertLess(run["summary"]["heart_rate_coverage"], 1)

    def test_reproducible_exports_and_csv_json_alignment(self):
        first = export_files(build_dataset())
        self.assertEqual(first, export_files(build_dataset()))
        dataset = json.loads(first["ridge-traverse.json"])
        for run in dataset["activities"]:
            rows = list(csv.DictReader(io.StringIO(first[f"{run['id']}.csv"].decode("utf-8"))))
            self.assertEqual(len(rows), len(run["samples"]))
            for row, record in zip(rows, run["samples"]):
                self.assertEqual(row["dataset_type"], "synthetic")
                self.assertEqual(row["sample_index"], str(record["index"]))
                self.assertEqual(row["processing_version"], dataset["metadata"]["processing_version"])
                for annotation in ("units", "generation", "assumptions"):
                    self.assertEqual(json.loads(row[f"{annotation}_json"]), dataset["metadata"][annotation])
                for key, value in (record["source"] | record["derived"]).items():
                    self.assertEqual(None if row[key] == "" else float(row[key]), value)
                for key, status in record["quality"].items():
                    self.assertEqual(row[f"{key}_quality"], status)


class LocalHTTPTests(unittest.TestCase):
    def test_server_and_export_reject_non_synthetic_metadata(self):
        dataset = {"metadata": {"dataset_type": "recorded"}}
        for operation in (lambda: create_server(0, dataset), lambda: export_files(dataset)):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "Only the synthetic dataset"):
                operation()

    def test_loopback_serving_and_downloads(self):
        dataset = build_dataset()
        exports = export_files(dataset)
        with create_server(0, dataset) as server:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(f"{base}/", timeout=5) as response:
                    self.assertIn(b"Activity Explorer", response.read())
                with urlopen(f"{base}/api/dataset", timeout=5) as response:
                    self.assertEqual(response.read(), exports["ridge-traverse.json"])
                for filename, content in exports.items():
                    with urlopen(f"{base}/exports/{filename}", timeout=5) as response:
                        self.assertEqual(response.headers["Content-Disposition"], f'attachment; filename="{filename}"')
                        self.assertEqual(response.read(), content)
                with urlopen(Request(f"{base}/app.js", method="HEAD"), timeout=5) as response:
                    self.assertEqual(response.read(), b"")
                    self.assertGreater(int(response.headers["Content-Length"]), 0)
                for path in ("/README.md", "/private-data/route.fit", "/leaflet.js", "/mapbox-logo"):
                    with self.subTest(path=path), self.assertRaises(HTTPError) as missing:
                        urlopen(base + path, timeout=5)
                    with missing.exception as response:
                        self.assertEqual(response.code, 404)
            finally:
                server.shutdown()
                thread.join()
