import unittest

from athlete import athlete_demo
from insights import profile_takeaway
from portfolio import public_portfolio
from semantics import (climb_state, load_state, pace_state, percentile, readiness_state,
                       thermal_state, trend_state, wind_state, workout_state)
from synthetic_data import build_dataset


class ClassificationTests(unittest.TestCase):
    def test_readiness_band_edges_and_partial_components(self):
        parts = athlete_demo()["health"]["latest"]["components"]
        for number, expected in ((0, "low"), (39, "low"), (40, "reduced"), (59, "reduced"),
                                 (60, "moderate"), (79, "moderate"), (80, "high"), (100, "high")):
            self.assertEqual(readiness_state(number, parts)["category"], expected)
        for number, components in ((-1, parts), (101, parts), (None, parts), (87, parts[:3])):
            self.assertEqual(readiness_state(number, components)["sufficiency"], "insufficient")

    def test_load_ratio_boundary_and_no_reference(self):
        for ratio, expected in ((.799, "lighter"), (.8, "typical"), (1.2, "typical"),
                                (1.201, "elevated"), (1.50, "elevated"), (1.501, "substantial")):
            self.assertEqual(load_state(ratio, 1)["category"], expected)
        self.assertEqual(load_state(400, 0)["tone"], "unavailable")

    def test_pace_sign_boundaries_and_small_cohorts(self):
        for pace, expected in ((285, "much_faster"), (286, "faster"), (294, "near"), (306, "near"),
                               (307, "slower"), (315, "much_slower")):
            self.assertEqual(pace_state(pace, 300, 5, "same-route")["category"], expected)
        self.assertEqual(pace_state(280, 300, 5, "same-route")["tone"], "positive")
        self.assertIsNone(pace_state(280, 300, 4, "same-route")["value"])
        self.assertIsNone(pace_state(280, None, 5, "same-route")["value"])

    def test_ranking_ties_and_same_sport_ascent(self):
        self.assertEqual(percentile(3, [1, 2, 3, 3, 5]), 60)
        self.assertEqual(percentile(3, [1, 2, 3, 3, 5], lower_better=True), 40)
        self.assertIsNone(percentile(3, [1, 2, 3, 4]))
        peers = [{"sport": "cycling", "distance_m": 25000, "ascent_m": 25 * i} for i in range(1, 11)]
        for rate, label in ((1, "low"), (5, "typical"), (9, "high"), (10, "exceptional")):
            s = climb_state({"sport": "cycling", "distance_m": 20000, "ascent_m": 20 * rate}, peers)
            self.assertEqual(s["category"], label)
            self.assertEqual(s["value"], rate)
        excluded = climb_state({"sport": "running", "distance_m": 6000, "ascent_m": 60}, peers)
        self.assertEqual(excluded["sufficiency"], "insufficient")
        self.assertEqual(excluded["value"], 10)

    def test_thermal_context_has_no_meteorological_index(self):
        for temp, expected in ((9.9, "cool"), (10, "mild"), (20, "warm"), (25, "elevated"), (30, "high")):
            result = thermal_state(temp, "Historical air temperature estimate")
            self.assertEqual(result["category"], expected)
            self.assertIsNone(result["evidence"]["meteorological_heat_index"])
            self.assertNotEqual(result["tone"], "negative")
        self.assertEqual(thermal_state(34)["tone"], "unavailable")

    def test_wind_projection_demand_retains_sign_semantics_and_coverage(self):
        bins = [
            {"width_m": 40, "reference_headwind_mps": -8, "reference_crosswind_mps": -3},
            {"width_m": 60, "reference_headwind_mps": 4, "reference_crosswind_mps": 3},
        ]
        archived = wind_state(bins, archived=True)
        self.assertAlmostEqual(archived["evidence"]["positive_headwind_mps"], 2.4)
        self.assertEqual(archived["evidence"]["absolute_crosswind_mps"], 3)
        self.assertEqual(archived["provenance"], "Fixed archived vector")
        self.assertEqual(archived["tone"], "caution")
        self.assertEqual(wind_state(bins)["tone"], "unavailable")
        self.assertEqual(wind_state(bins + [{"width_m": 26}], archived=True)["tone"], "unavailable")

    def test_fitness_trends_apply_direction_and_noise_gates(self):
        self.assertEqual(trend_state("benchmark", [294, 294], [300, 300], lower_better=True, relative=True)["category"], "stable")
        self.assertEqual(trend_state("benchmark", [290, 290], [300, 300], lower_better=True, relative=True)["category"], "improving")
        self.assertEqual(trend_state("vo2max", [49, 50], [46, 47])["category"], "improving")
        self.assertEqual(trend_state("vo2max", [47], [46, 47])["sufficiency"], "insufficient")
        self.assertEqual(trend_state("resting_hr", [61] * 5, [56] * 14)["category"], "higher")
        self.assertEqual(trend_state("hrv", [63] * 5, [56] * 14)["tone"], "neutral")
        self.assertEqual(trend_state("hrv", [None, 64], [56, 57])["tone"], "unavailable")

    def test_workout_inference_requires_physiology_and_modest_ascent_for_recovery(self):
        ref = [{"sport": "running", "heart_bpm": 147, "heart_coverage": .95, "pace_s_per_km": 300,
                "distance_m": 6000, "ascent_m": 60} for _ in range(5)]
        run = {**ref[0], "heart_bpm": 137, "pace_s_per_km": 321}
        modest = climb_state(run, ref)
        self.assertEqual(workout_state(run, ref, ref, modest)["category"], "recovery")
        self.assertEqual(workout_state({**run, "heart_bpm": None}, ref, ref, modest)["tone"], "unavailable")
        self.assertEqual(workout_state({**run, "heart_coverage": .79}, ref, ref, modest)["tone"], "unavailable")
        self.assertNotEqual(workout_state({**run, "heart_bpm": 147}, ref, ref, modest)["category"], "recovery")
        self.assertEqual(workout_state({**run, "heart_bpm": 155, "pace_s_per_km": 282}, ref, ref, modest)["category"], "higher_intensity")


class InsightTests(unittest.TestCase):
    def test_missing_fitness_evidence_withholds_positive_trend_language(self):
        data = athlete_demo()
        health = data["health"]
        health["semantic"]["benchmark"] = trend_state("benchmark", [1400], [1510, 1520])
        health["semantic"]["readiness"] = readiness_state(81, [])
        takeaway = profile_takeaway(health, data["profile"])
        self.assertIn("insufficient trend evidence", takeaway["text"])
        self.assertNotIn("both improved", takeaway["text"])
        self.assertNotIn("Readiness", dict(takeaway["facts"]))

    def test_cohort_evidence_changes_takeaways_without_inferring_fitness_from_a_ride(self):
        portfolio = public_portfolio(build_dataset())
        fast = portfolio.detail("ridge-8")
        slow = portfolio.detail("ridge-1")
        self.assertLess(fast["semantic"]["route_pace"]["value"], 0)
        self.assertGreater(slow["semantic"]["route_pace"]["value"], 0)
        self.assertIn("comparable recorded effort", fast["takeaway"]["text"])
        self.assertTrue(any("cannot establish a fitness trend" in text for _, text in fast["takeaway"]["facts"]))
        self.assertNotIn("stronger performance", slow["takeaway"]["text"])
        ride = portfolio.detail("foothills")
        self.assertIn("too few to rank", ride["takeaway"]["text"])
        self.assertEqual(ride["semantic"]["climb"]["tone"], "unavailable")
        self.assertIn("Fictional weather", dict(ride["takeaway"]["facts"]))

    def test_scenario_semantics_keep_score_and_use_disjoint_windows(self):
        typical, compressed = athlete_demo(), athlete_demo("compressed")
        for data, score, category in ((typical, 81, "typical"), (compressed, 61, "elevated")):
            health = data["health"]
            self.assertEqual(health["semantic"]["readiness"]["value"], score)
            self.assertEqual(health["semantic"]["load"]["category"], category)
            earlier = sum(day["session_load"] for day in health["daily"][-36:-8]) / 4
            self.assertAlmostEqual(earlier, health["semantic"]["load"]["reference"])
            self.assertEqual(data["planner"]["baseline"]["semantic"]["load"], health["semantic"]["load"])
        self.assertIn("conservative", compressed["takeaway"]["text"])
        self.assertNotIn("conservative", typical["takeaway"]["text"])
