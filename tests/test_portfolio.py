from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
import struct
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
import json

from app import create_server, json_bytes, mapbox_options
from athlete import athlete_demo
from portfolio import public_portfolio, similar_context, similar_runs
from private_preview import build_private_portfolio, cohort_files, staged_review_cohort
from synthetic_data import build_dataset
from test_private_preview import definition, fit_file


def six_kilometre_fit(start, north=0):
    activity = definition(0, 0, [(0, 1, 0)]) + b"\x00\x04"
    activity += definition(1, 18, [(2, 4, 0x86), (5, 1, 0), (7, 4, 0x86), (8, 4, 0x86), (9, 4, 0x86)])
    activity += b"\x01" + struct.pack("<IBIII", start, 1, 1_500_000, 1_500_000, 600_000)
    activity += definition(2, 20, [(253, 4, 0x86), (0, 4, 0x85), (1, 4, 0x85),
                                    (5, 4, 0x86), (3, 1, 0x02)])
    for i in range(61):
        activity += b"\x02" + struct.pack("<IiiIB", start + 25 * i, north, 10729 * i, 10_000 * i, 143)
    return fit_file(activity)


class PortfolioTests(unittest.TestCase):
    def test_default_cohort_is_scoped_to_staged_private_reviews(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            review = root / "review"
            manifest = review / "cohort" / "selection.json"
            with patch("private_preview.PRIVATE_ROOT", root):
                self.assertIsNone(staged_review_cohort([review / "run.fit"]))
                manifest.parent.mkdir(parents=True)
                manifest.write_text('{"files":["run.fit"]}', encoding="utf-8")
                self.assertEqual(staged_review_cohort([review / "run.fit"]), manifest)
                self.assertIsNone(staged_review_cohort([root / "other.fit"]))



    def test_private_cohort_rechecks_overlap_dates_and_duplicates(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            anchor = root / "anchor.fit"
            candidates = root / "cohort"
            candidates.mkdir()
            anchor.write_bytes(six_kilometre_fit(1_000_000_000))
            (candidates / "repeat.fit").write_bytes(six_kilometre_fit(1_000_086_400, 100))
            (candidates / "distant.fit").write_bytes(six_kilometre_fit(1_000_172_800, 108_000))
            (candidates / "duplicate.fit").write_bytes(anchor.read_bytes())
            with patch("private_preview.PRIVATE_ROOT", root):
                _, _, model = build_private_portfolio([anchor], cohort=candidates)
            self.assertEqual(model.index()["cohort"], {"candidates": 3, "accepted": 1})
            self.assertEqual(len(model.index()["history"]), 2)
            self.assertTrue(all(row["date"] for row in model.index()["history"]))
            ref = model.detail("run-1")["peer_context"]
            self.assertEqual(ref["same_route"]["count"], 1)
            self.assertIsNone(ref["same_route"]["percentile"])
            self.assertIsNone(ref["profile"]["bins"][5]["band"])


    def test_similar_distance_excludes_selection_sport_and_bad_measurements(self):
        selected = {"id": "run", "sport": "running", "distance_m": 6000, "pace_s_per_km": 300}
        rows = [selected, {**selected, "id": "close", "distance_m": 5500, "pace_s_per_km": 290},
                {**selected, "id": "too-far", "distance_m": 6501}, {**selected, "id": "cycle", "sport": "cycling"},
                {**selected, "id": "bad", "pace_s_per_km": None}]
        peers = similar_runs(selected, rows)
        self.assertEqual([a["id"] for a in peers], ["close"])
        self.assertEqual(similar_context(selected, peers), {"count": 1, "median": 290, "band": None, "percentile": None})
        percent = similar_context(selected, [{"pace_s_per_km": p} for p in [280, 290, 300, 310, 330]])
        self.assertEqual(percent["percentile"], 50)
        self.assertEqual(percent["band"], [290, 310])

    def test_fictional_cohort_has_similar_and_distinct_same_route_peers(self):
        model = public_portfolio(build_dataset())
        detail = model.detail("ridge-1")
        refs = detail["peer_context"]
        self.assertEqual(refs["similar"]["count"], 11)
        self.assertEqual(refs["same_route"]["count"], 9)
        self.assertNotIn("ridge-1", refs["peer_ids"])
        self.assertTrue(all(bin["width_m"] == 100 for bin in refs["profile"]["bins"]))
        bins = refs["profile"]["bins"]
        self.assertEqual(bins[len(bins) // 2]["count"], 9)
        self.assertLess(min(bin["count"] for bin in bins), 9)
        self.assertTrue(all((bin["band"] is not None) == (bin["count"] >= 4) for bin in bins))
        self.assertEqual(detail["peer_weather"]["wind_speed_mps"]["count"], 9)
        self.assertIsNone(detail["positions"])

    def test_demo_labels_match_history_explorer_and_comparisons(self):
        model = public_portfolio(build_dataset())
        expected = {
            "west-run": "5 km Demo Run 01",
            "east-run": "5 km Demo Run 02",
            **{f"ridge-{i}": f"6 km Demo Run {i:02d}" for i in range(1, 13)},
            "foothills": "35 km Demo Ride 01",
        }
        self.assertEqual({row["id"]: row["name"] for row in model.index()["history"]}, expected)
        for activity_id in ("west-run", "ridge-1", "foothills"):
            self.assertEqual(model.detail(activity_id)["activity"]["name"], expected[activity_id])
        fixed = model.detail("west-run")["pair"]["running"]["runs"]
        self.assertEqual([run["name"] for run in fixed], [expected["west-run"], expected["east-run"]])
        peer = model.compare_runs("ridge-1", "ridge-2")["running"]["runs"]
        self.assertEqual([run["name"] for run in peer], [expected["ridge-1"], expected["ridge-2"]])
        self.assertEqual(model.detail("foothills")["cycling"]["name"], expected["foothills"])

    def test_bounded_cohort_selection_and_map_configuration_paths(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            selection = root / "selection.json"
            token = root / "test-token.txt"
            logo = root / "logo.svg"
            selection.write_text('{"files":["run.fit"]}')
            token.write_text("pk.test.fixture")
            logo.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
            with patch("private_preview.PRIVATE_ROOT", root):
                self.assertEqual(cohort_files(selection), [root / "run.fit"])
                self.assertEqual(mapbox_options(token, logo)[0], "pk.test.fixture")
                selection.write_text('{"files":["../elsewhere.fit"]}')
                with self.assertRaisesRegex(ValueError, "Invalid cohort"):
                    cohort_files(selection)
                token.write_text("sk.test.fixture")
                with self.assertRaisesRegex(ValueError, "public pk"):
                    mapbox_options(token, logo)

    def test_public_http_history_never_exposes_private_map_configuration(self):
        with create_server(0, build_dataset(), mapbox=("pk.test.fixture", b"test", "image/png")) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(base + "/api/portfolio", timeout=5) as response:
                    data = json.load(response)
                    self.assertEqual(data["map"], {"leaflet": False, "satellite": None})
                    self.assertEqual(len(data["history"]), 15)
                    self.assertNotIn("api.mapbox.com", response.headers["Content-Security-Policy"])
                with urlopen(base + "/api/athlete", timeout=5) as response:
                    self.assertEqual(response.read(), json_bytes(athlete_demo()))
            finally:
                server.shutdown()
                thread.join()

    def test_running_pair_endpoint_uses_same_route_peers_and_preserves_original_pair(self):
        dataset = build_dataset()
        selected = dataset["activities"][0]["id"]
        original_peer = dataset["activities"][1]["id"]
        with create_server(0, dataset) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}/api/activities"
                with urlopen(f"{base}/ridge-1/compare/ridge-2", timeout=5) as response:
                    pair = json.load(response)
                self.assertEqual(pair["run_ids"], ["ridge-1", "ridge-2"])
                self.assertTrue(pair["synthetic"])
                self.assertIsNone(pair["provenance"]["weather"])
                self.assertTrue(pair["running"]["available"])
                self.assertGreaterEqual(pair["running"]["distance_m"], 3000)
                self.assertTrue(all(run["mean_heart_bpm"] for run in pair["running"]["runs"]))
                for peer in ("ridge-1", "ridge-11", "foothills"):
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(f"{base}/ridge-1/compare/{peer}", timeout=5)
                    self.assertEqual(caught.exception.code, 404)
                with urlopen(f"{base}/{selected}", timeout=5) as response:
                    fixed = json.load(response)["pair"]
                self.assertEqual(fixed["run_ids"], [selected, original_peer])
                self.assertTrue(fixed["running"]["available"])
            finally:
                server.shutdown()
                thread.join()



class AthleteTests(unittest.TestCase):
    def test_fictional_health_windows_and_readiness_reconcile_with_underlying_sessions(self):
        from health import training_load

        data = athlete_demo()
        health = data["health"]
        samples = health["daily"]
        latest = health["latest"]
        self.assertEqual(latest["load_7"], sum(row["session_load"] for row in samples[-8:-1]))
        self.assertEqual(latest["load_28"], sum(row["session_load"] for row in samples[-29:-1]))
        self.assertAlmostEqual(sum(row["session_load"] for row in samples),
                               sum(training_load(row["duration_s"], row["rpe"]) for row in data["activities"]))
        self.assertTrue(all(row["readiness"] is None for row in samples[:28]))
        for point in samples[28:]:
            self.assertEqual(point["readiness"], round(sum(part["weight"] * part["score"] for part in point["components"])))
            self.assertTrue(0 <= point["readiness"] <= 100)
        expected = (3.5 + .2 * 5000 * 60 / health["vo2max"][-1]["benchmark_s"]) / .90
        self.assertAlmostEqual(expected, health["vo2max"][-1]["estimate"], places=1)

    def test_heavier_scenario_adapts_health_takeaway_and_planner_load(self):
        from health import training_load

        healthy, busier = athlete_demo(), athlete_demo("compressed")
        self.assertEqual(healthy["health"]["vo2max"], busier["health"]["vo2max"])
        self.assertLess(busier["health"]["recent"]["hrv_ms"], healthy["health"]["recent"]["hrv_ms"])
        self.assertLess(busier["health"]["recent"]["sleep_min"], healthy["health"]["recent"]["sleep_min"])
        self.assertGreater(busier["health"]["recent"]["load_7"], healthy["health"]["recent"]["load_7"])
        self.assertLess(busier["health"]["latest"]["readiness"], healthy["health"]["latest"]["readiness"])
        self.assertNotEqual(busier["takeaway"]["text"], healthy["takeaway"]["text"])
        normal, guarded = (data["planner"] for data in (healthy, busier))
        self.assertFalse(normal["baseline"]["volume_guard"])
        self.assertTrue(guarded["baseline"]["volume_guard"])
        self.assertTrue(normal["alternatives"][0]["paced"])
        self.assertFalse(guarded["alternatives"][0]["paced"])
        self.assertLess(guarded["alternatives"][0]["load"], normal["alternatives"][0]["load"])
        for plan in (normal, guarded):
            self.assertLess(plan["alternatives"][1]["load"], plan["alternatives"][0]["load"])
            for choice in plan["alternatives"]:
                self.assertEqual(choice["load"], round(sum(training_load(day["duration_s"], day["rpe"]) for day in choice["days"])))
                self.assertIn(f"{plan['baseline']['readiness']}/100", choice["takeaway"]["text"])
    def test_fixture_totals_and_records_reconcile_with_listed_activities(self):
        data = athlete_demo()
        self.assertEqual(data, athlete_demo())
        activities, profile = data["activities"], data["profile"]
        for sport in ("running", "cycling"):
            rows = [row for row in activities if row["sport"] == sport]
            self.assertEqual(profile["lifetime"][sport]["count"], len(rows))
            for field in ("distance_m", "duration_s"):
                self.assertEqual(profile["lifetime"][sport][field], sum(row[field] for row in rows))
                for period in ("monthly", "weekly"):
                    self.assertEqual(sum(p["totals"][sport][field] for p in profile[period]),
                                     profile["lifetime"][sport][field])
        benchmark = min(profile["benchmarks"], key=lambda row: row["duration_s"])
        self.assertEqual(profile["records"]["fastest_5k"], benchmark)
        self.assertTrue(all(row["distance_m"] == 5000 for row in profile["benchmarks"]))

    def test_plan_uses_recent_profile_and_dates_follow_the_history(self):
        data = athlete_demo()
        alternatives = data["planner"]["alternatives"]
        baseline = data["planner"]["baseline"]
        recent = data["profile"]["weekly"][-4:]
        self.assertEqual(baseline["median_run_m"], median(p["totals"]["running"]["distance_m"] for p in recent))
        for choice in alternatives:
            self.assertEqual(len(choice["days"]), 7)
            self.assertGreater(date.fromisoformat(choice["days"][0]["date"]), date.fromisoformat(data["through"]))
            self.assertLessEqual(choice["totals"]["running"], min(baseline["median_run_m"], baseline["last_run_m"]))
            for sport in ("running", "cycling"):
                self.assertEqual(choice["totals"][sport],
                                 sum(day["distance_m"] for day in choice["days"] if day["sport"] == sport))
        self.assertLess(alternatives[1]["totals"]["running"], alternatives[0]["totals"]["running"])
