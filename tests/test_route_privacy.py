from math import degrees
from random import Random
import unittest

from environmental import EARTH_RADIUS_M, geographic_distance
from route_privacy import BUNDLE_KIND, MASK_PADDING_M, build_recorded_portfolio, retain_sections
from tools.prepare_recorded_review import audit_sections


def track(x_values):
    samples = []
    facts = []
    for t, x in enumerate(x_values):
        samples.append({"source": {"elapsed_s": t * 5, "speed_mps": 4, "heart_rate_bpm": 142,
                                   "elevation_m": 50 + t / 10}})
        facts.append({"lat_lon": (0, degrees(x / EARTH_RADIUS_M))})
    return samples, facts


def review_fixture():
    outward = list(range(0, 4601, 50))
    samples, facts = track([*outward, *outward[-2::-1], *outward[1:]])
    centres = [facts[0]["lat_lon"], facts[-1]["lat_lon"]]
    run = retain_sections(samples, facts, centres, 1000, rng=Random(18))
    # Two matched recordings and a ride are sufficient to exercise every payload.
    bundle = {"kind": BUNDLE_KIND, "activities": [
        {"sport": "running", "sections": run[:1]},
        {"sport": "running", "sections": run[:1]},
        {"sport": "cycling", "sections": run},
    ]}
    return bundle, centres


class RoutePrivacyTests(unittest.TestCase):
    def test_all_passes_at_both_ends_are_retained_as_separate_sections(self):
        bundle, centres = review_fixture()
        sections = bundle["activities"][-1]["sections"]
        self.assertEqual(len(sections), 3)
        observed = {tuple(row["lat_lon"]) for row in track(range(0, 4601, 50))[1]}
        for section in sections:
            self.assertEqual(section[0][2], 0)
            for row in section:
                self.assertIn(tuple(row[:2]), observed)
                self.assertTrue(all(geographic_distance(row[:2], centre) > 1200 for centre in centres))
        self.assertEqual(audit_sections(bundle["activities"], centres, 1000)["edge_exclusion_check"], "passed")

    def test_edge_crossing_is_cut_even_with_both_observations_outside(self):
        left = list(range(-5000, -1999, 50))
        right = list(range(2000, 5001, 50))
        samples, facts = track([*left, *right])
        sections = retain_sections(samples, facts, [(0, 0)], 1000, rng=Random(4))
        self.assertEqual(len(sections), 2)
        self.assertTrue(all(row[1] < 0 for row in sections[0]))
        self.assertTrue(all(row[1] > 0 for row in sections[1]))
        with self.assertRaisesRegex(ValueError, "at least 1,000"):
            retain_sections(samples, facts, [(0, 0)], 999)

    def test_a_zone_from_another_recording_masks_the_entire_set(self):
        samples, facts = track(range(1000, 9501, 50))
        foreign_end = (0, degrees(5000 / EARTH_RADIUS_M))
        sections = retain_sections(samples, facts, [(0, 0), foreign_end], 1000, rng=Random(5))
        self.assertEqual(len(sections), 2)
        self.assertTrue(all(geographic_distance(row[:2], foreign_end) > 1200 for part in sections for row in part))

    def test_smaller_ignored_reviews_require_explicit_opt_in_and_keep_edge_clearance(self):
        samples, facts = track(range(0, 9501, 50))
        centres = [(0, 0), (0, degrees(5000 / EARTH_RADIUS_M))]
        for radius in (500, 750):
            with self.subTest(radius=radius):
                with self.assertRaises(ValueError):
                    retain_sections(samples, facts, centres, radius)
                sections = retain_sections(samples, facts, centres, radius, experimental=True, rng=Random(5))
                self.assertEqual(len(sections), 2)
                self.assertEqual(audit_sections([{"sections": sections}], centres, radius + MASK_PADDING_M)
                                 ["edge_exclusion_check"], "passed")
        with self.assertRaises(ValueError):
            retain_sections(samples, facts, centres, 499, experimental=True)

    def test_masked_distances_timing_and_elevation_do_not_bridge_removed_intervals(self):
        bundle, _ = review_fixture()
        dataset, comparison, model = build_recorded_portfolio(bundle)
        ride = dataset["activities"][-1]
        sections = bundle["activities"][-1]["sections"]
        self.assertEqual(sum(row["break_before"] for row in ride["samples"]), 2)
        self.assertEqual(len(comparison["cycling"]["routes"]), 3)
        self.assertEqual([len(trace) for trace in comparison["cycling"]["routes"]], list(map(len, sections)))
        distance = sum(geographic_distance(a[:2], b[:2]) for part in sections for a, b in zip(part, part[1:]))
        self.assertAlmostEqual(ride["summary"]["distance_m"], distance, places=4)
        self.assertEqual(ride["summary"]["elapsed_s"], sum(row[2] for part in sections for row in part))
        ascent = sum(max(0, b[5] - a[5]) for part in sections for a, b in zip(part, part[1:]))
        self.assertAlmostEqual(ride["summary"]["elevation_gain_m"], ascent)
        self.assertAlmostEqual(model.history[ride["id"]]["heart_bpm"], 142)
        self.assertIsNone(comparison["cycling"]["activity_weather"])
        self.assertIsNone(comparison["cycling"]["recorded_ascent_m"])
        runs = [row["id"] for row in model.history.values() if row["sport"] == "running"]
        pair = model.compare_runs(*runs)["running"]
        self.assertGreaterEqual(pair["distance_m"], 1000)
        self.assertLessEqual(pair["distance_m"], model.history[runs[0]]["distance_m"])
        self.assertEqual(pair["runs"][0]["heart_coverage"], 1)

    def test_bundle_loader_rejects_raw_or_additional_metadata(self):
        bundle, _ = review_fixture()
        with self.assertRaises(ValueError):
            build_recorded_portfolio({"metadata": {"dataset_type": "private-fit-preview"}, "activities": []})
        bundle["activities"][0]["original_start"] = [-45, 1]
        with self.assertRaises(ValueError):
            build_recorded_portfolio(bundle)

    def test_several_close_arc_approaches_raise_a_joint_review_flag(self):
        entries = [{"sections": [
            [[.014, 0], [.016, 0]], [[0, .014], [0, .016]], [[-.014, 0], [-.016, 0]],
        ]}]
        self.assertEqual(audit_sections(entries, [(0, 0)], 1000)["multi_approach_patterns_for_review"], 1)