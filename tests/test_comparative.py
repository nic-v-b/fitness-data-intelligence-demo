import json
from math import pi
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from analysis_core import Sample, process_samples
from app import create_server, export_files, json_bytes
from comparative import build_comparative, cycling_analysis, grade_percent, running_comparison, strongest_climb
from environmental import EARTH_RADIUS_M, Observations, Sources, geographic_distance, heading_deg, wind_components
from geography import match_route, route_parts
from synthetic_data import build_dataset
from test_private_preview import activity_fit


def route(name, points, *, speed=4, times=None, heart=140, breaks=(), elevations=None):
    samples = [Sample(times[i] if times else i * 10 / speed, i * 10, x, y, speed,
                      heart[i] if isinstance(heart, list) else heart, elevations[i] if elevations else None)
               for i, (x, y) in enumerate(points)]
    records = process_samples(samples)
    for index in breaks:
        records[index]["route_break_before"] = True
    return {"name": name, "samples": records}


def straight(start=0, end=101, **kwargs):
    return route("Reference", [(x * 10, 0) for x in range(start, end)], **kwargs)


def source_block(points, *, weather=True):
    result = {"provider": "Reference provider", "product": "Validation product",
              "source_kind": "station observation" if weather else "terrain model",
              "resolution": "1 hour" if weather else "30 m grid", "reference": "public testing fixture",
              "max_distance_m": 1000, "points": points}
    if weather:
        result["max_time_offset_s"] = 1800
    return result


class RunningTests(unittest.TestCase):
    def test_forward_alignment_using_geometry_with_offset_and_different_sampling(self):
        a = straight()
        b = route("Offset", [(x, 3) for x in range(175, 826, 5)])
        _, _, aligned = match_route(route_parts(a), route_parts(b))
        self.assertGreaterEqual(aligned[0].a_m, 160)
        self.assertLessEqual(aligned[-1].a_m, 840)
        interior = [link for link in aligned if 200 <= link.a_m <= 800]
        for link in interior:
            self.assertAlmostEqual(link.b_m + 175, link.a_m, delta=0.01)
            self.assertAlmostEqual(link.separation_m, 3)

    def test_reverse_crossing_and_parallel_outside_tolerance(self):
        a = route_parts(straight())
        reverse = route("Reverse", [(i, 0) for i in range(1000, -1, -10)])
        crossing = route("Crossing", [(500, i) for i in range(-500, 501, 10)])
        parallel = route("Parallel", [(i, 16) for i in range(0, 1001, 10)])
        for run in (reverse, crossing, parallel):
            self.assertIsNone(match_route(a, route_parts(run)), run["name"])

    def test_nearby_stretches_cannot_bridge_a_discontinuity(self):
        first = straight(end=65, breaks=(33,))
        second = straight(end=65)
        self.assertIsNone(match_route(route_parts(first), route_parts(second)))

    def test_pace_and_time_weighted_heart_rate(self):
        a = straight(speed=4, heart=140)
        b = straight(speed=5, heart=[None] * 20 + [160] * 81)
        analysis = running_comparison([a, b], [None, None], Sources(), False)
        self.assertEqual(analysis["distance_m"], 1000)
        self.assertEqual(analysis["runs"][0]["moving_s"], 250)
        self.assertEqual(analysis["runs"][0]["elapsed_s"], 250)
        self.assertEqual(analysis["runs"][1]["pace_s_per_km"], 200)
        self.assertEqual(analysis["runs"][1]["mean_heart_bpm"], 160)
        self.assertAlmostEqual(analysis["runs"][1]["heart_coverage"], .8)
        self.assertAlmostEqual(analysis["pace_change_fraction"], -.2)
        self.assertEqual(analysis["bins"][0]["distance_m"], 25)
        self.assertEqual(analysis["bins"][0]["values"][1]["pace_s_per_km"], 200)
        self.assertIsNone(analysis["bins"][0]["values"][1]["mean_heart_bpm"])
        self.assertIsNone(analysis["runs"][0]["air_temperature_c"])
        self.assertEqual(analysis["runs"][0]["headwind_mps_coverage"], 0)

    def test_stationary_pauses_exclude_elapsed_gap_from_pace_and_signal_means(self):
        a = route("Paused", [(0, 0), (100, 0), (100, 0), (200, 0)], times=[0, 20, 80, 100],
                  heart=[110, 130, 150, 170], breaks=(2,))
        context = [{"temperature_c": 18}, {"temperature_c": 20},
                   {"temperature_c": 24, "stationary_pause_s": 60}, {"temperature_c": 26}]
        part, = route_parts(a, context)
        full = part.interval(0, 200)
        self.assertEqual(full["moving_s"], 40)
        self.assertEqual(full["elapsed_s"], 100)
        self.assertEqual(full["heart_integral"] / full["heart_s"], 140)
        self.assertEqual(full["device_temp_integral"] / full["device_temp_s"], 22)
        self.assertEqual(part.interval(0, 100)["elapsed_s"], 20)
        self.assertEqual(part.interval(100, 200)["elapsed_s"], 80)
        self.assertEqual(len(route_parts(a)), 2)


class EnvironmentalTests(unittest.TestCase):
    def test_archived_reference_wind_changes_sign_without_creating_local_weather_coverage(self):
        start = 1_704_067_200
        points = [(i * 10, 0) for i in range(61)] + [(600 - i * 10, 100) for i in range(61)]
        east_west = route("Reference", points, breaks=(61,))
        context = [{"utc_s": start + sample["source"]["elapsed_s"] + 2} for sample in east_west["samples"]]
        for sample in east_west["samples"]:
            sample["source"]["elapsed_s"] += 2
        weather = {"provider": "Reference archive", "product": "Test product",
                   "source_kind": "historical estimate", "resolution": "Full activity",
                   "reference": "Fixture", "summaries": [{
                       "activity_start_utc": "2024-01-01T00:00:00Z", "source_sample_count": 122,
                       "spatial_anchor_count": 2,
                       "field_sample_counts": {"air_temperature_c": 122, "wind_speed_mps": 122, "wind_from_deg": 122},
                       "air_temperature_c": 18, "wind_speed_mps": 6, "wind_from_deg": 90,
                   }]}
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "weather.json"
            path.write_text(json.dumps({"schema_version": 1, "activity_weather": weather}))
            sources = Sources.load(path, root)
            result = cycling_analysis(east_west, context, sources, False)
            self.assertEqual(result["bins"][0]["reference_headwind_mps"], 6)
            self.assertEqual(result["bins"][-1]["reference_headwind_mps"], -6)
            self.assertAlmostEqual(result["bins"][-1]["reference_crosswind_mps"], 0)
            self.assertTrue(all(bin["headwind_mps"] is None for bin in result["bins"]))
            self.assertEqual(result["environment"]["headwind_mps_coverage"], 0)
            self.assertEqual(result["activity_weather"]["air_temperature_c"], 18)
            self.assertIsNone(sources.activity_weather_at(start + 1))
            self.assertNotIn("activity_start_utc", json_bytes(result).decode())
            self.assertEqual(sources.provenance()["activity_weather"]["resolution"], "Full activity")
            weather["summaries"][0]["field_sample_counts"]["wind_speed_mps"] = 123
            path.write_text(json.dumps({"schema_version": 1, "activity_weather": weather}))
            with self.assertRaisesRegex(ValueError, "Invalid local environmental"):
                Sources.load(path, root)

    def test_vector_cardinals_and_units(self):
        self.assertAlmostEqual(geographic_distance((0, 0), (0, 1)), pi * EARTH_RADIUS_M / 180)
        self.assertEqual(heading_deg(0, 8), 0)
        self.assertEqual(heading_deg(4, 0), 90)
        self.assertEqual(heading_deg(-4, 0), 270)
        self.assertIsNone(heading_deg(0, 0))
        for from_deg, travel, expected in (
            (90, 90, (10, 0)), (270, 90, (-10, 0)), (0, 90, (0, 10)), (180, 90, (0, -10)),
            (0, 45, (10 / 2**.5, 10 / 2**.5)),
        ):
            for actual, value in zip(wind_components(10, from_deg, travel), expected):
                self.assertAlmostEqual(actual, value)
        self.assertEqual(wind_components(0, None, None), (0, 0))
        self.assertEqual(wind_components(5, None, 45), (None, None))
        self.assertEqual(grade_percent(100, 106, 200), 3)
        self.assertEqual(grade_percent(106, 100, 200), -3)
        self.assertIsNone(grade_percent(100, None, 200))

    def test_source_time_and_space_alignment_and_provenance(self):
        base = 1_704_067_200
        weather = source_block([
            {"time_utc": "2024-01-01T00:00:00Z", "latitude_deg": 0, "longitude_deg": 0,
             "air_temperature_c": 2, "wind_speed_mps": 4, "wind_from_deg": 90},
            {"time_utc": "2024-01-01T01:00:00Z", "latitude_deg": 0, "longitude_deg": 0,
             "air_temperature_c": 5},
            {"time_utc": "2024-01-01T01:00:00Z", "latitude_deg": 0, "longitude_deg": 0.04,
             "air_temperature_c": 7},
        ])
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "observations.json"
            path.write_text(json.dumps({"schema_version": 1, "weather": weather}))
            sources = Sources.load(path, root)
            self.assertEqual(sources.weather_at((0, 0), base)["air_temperature_c"], 2)
            self.assertEqual(sources.weather_at((0, .04), base + 3600)["air_temperature_c"], 7)
            self.assertEqual(sources.weather_at((0, 0), base + 3600)["wind_speed_mps"], None)
            self.assertEqual(sources.weather_at((0, 0), base + 7200), {})
            self.assertEqual(sources.weather_at((0, .02), base + 3600), {})
            self.assertEqual(sources.provenance()["weather"]["source_kind"], "station observation")
            self.assertEqual(sources.provenance()["weather"]["max_time_offset_s"], 1800)
            self.assertNotIn("time_utc", json_bytes(sources.provenance()).decode())
            self.assertIsNone(sources.provenance()["terrain"])
            with self.assertRaisesRegex(ValueError, "inside the ignored"):
                Sources.load(path, root / "another")
            weather["points"][0]["time_utc"] = "2024-01-01T00:00:00"
            path.write_text(json.dumps({"schema_version": 1, "weather": weather}))
            with self.assertRaisesRegex(ValueError, "Invalid local environmental"):
                Sources.load(path, root)

    def test_ride_links_speed_to_grade_and_distinct_elevation_sources(self):
        route_data = straight(end=31, speed=10, elevations=[100 + i / 2 for i in range(31)])
        context = [{"lat_lon": (0, i * .0001), "utc_s": 1_704_067_200 + i} for i in range(31)]
        weather = Observations(source_block([{"time_utc": "2024-01-01T00:00:00Z",
            "latitude_deg": 0, "longitude_deg": 0, "wind_speed_mps": 6, "wind_from_deg": 90}]), weather=True)
        model = Observations(source_block([{"latitude_deg": 0, "longitude_deg": i * .0001,
            "elevation_m": 200 - i} for i in range(31)], weather=False), weather=False)
        result = cycling_analysis(route_data, context, Sources(weather, model), False)
        first = result["bins"][0]
        self.assertAlmostEqual(first["speed_kmh"], 36)
        self.assertEqual(first["elevation_m"], 102.5)
        self.assertEqual(first["recorded_grade_pct"], 5)
        self.assertEqual(first["terrain_m"], 195)
        self.assertEqual(first["terrain_grade_pct"], -10)
        self.assertEqual(first["headwind_mps"], 6)
        self.assertEqual(result["environment"]["headwind_mps_coverage"], 1)

    def test_climb_rejects_cross_gap_windows_and_uses_distance_over_total_time(self):
        bins = [{"width_m": 100, "distance_m": i * 100 + 50, "recorded_grade_pct": 20 if i < 4 else 5,
                 "break_before": i in (0, 4), "speed_kmh": 10 if i == 4 else 20}
                for i in range(9)]
        climb = strongest_climb(bins)
        self.assertEqual(climb["distance_m"], 650)
        self.assertEqual(climb["grade_pct"], 5)
        self.assertAlmostEqual(climb["speed_kmh"], 500 / 30)


class ComparativeIntegrationTests(unittest.TestCase):

    def test_public_fixture_reproducible_and_private_endpoint_has_no_export(self):
        dataset = build_dataset()
        first = build_comparative(dataset["activities"], synthetic=True)
        self.assertEqual(json_bytes(first), json_bytes(build_comparative(dataset["activities"], synthetic=True)))
        self.assertTrue(first["running"]["available"])
        self.assertTrue(first["cycling"]["available"])
        self.assertEqual(first["provenance"]["weather"]["source_kind"], "synthetic")
        self.assertEqual(first["cycling"]["environment"]["headwind_mps_coverage"], 1)
        self.assertNotIn("comparative", json.loads(export_files(dataset)["ridge-traverse.json"]))

        private = {"metadata": {"dataset_type": "private-fit-preview"}, "activities": []}
        marker = {"synthetic": False, "test": "only served from loopback"}
        with create_server(0, private, marker) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(url + "/api/comparative", timeout=5) as response:
                    self.assertEqual(json.load(response), marker)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                for request, status in (
                    (Request(url + "/api/comparative", headers={"Host": "remote.example"}), 403),
                    (url + "/exports/ridge-traverse.json", 404),
                    (url + "/private-data/review/observations.json", 404),
                ):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request, timeout=5)
                    self.assertEqual(error.exception.code, status)
                    error.exception.close()
            finally:
                server.shutdown()
                thread.join()
