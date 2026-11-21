from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from route_privacy import build_recorded_portfolio, load_recorded_review
from test_route_privacy import review_fixture
from tools.recorded_review_integrator import combine_protected_runs_and_full_ride


class ProtectedBundleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.bundle, _ = review_fixture()
        self.dataset, self.comparison, self.original = build_recorded_portfolio(self.bundle)
        self.old_ride = next(activity for activity in self.dataset["activities"]
                             if activity["sport"] == "cycling")
        self.full_context = deepcopy(self.original.contexts[self.old_ride["id"]])
        self.full_ride = deepcopy(self.old_ride)

    def test_full_cycling_replacement_retains_masked_running_observations(self):
        # Simulate a complete ride that retains the reviewed trace but whose
        # original session aggregates exceed those of the clipped version.
        self.full_ride["id"], self.full_ride["name"] = "ride", "Ride"
        self.full_ride["diagnostics"] = {
            "session_distance_m": self.old_ride["summary"]["distance_m"] + 3100,
            "session_timer_s": self.old_ride["summary"]["elapsed_s"] + 500,
            "session_ascent_m": self.old_ride["summary"]["elevation_gain_m"] + 25,
        }
        data, comparative, model = combine_protected_runs_and_full_ride(
            self.dataset, self.original, self.full_ride, self.full_context
        )
        runs_before = [activity for activity in self.dataset["activities"]
                       if activity["sport"] == "running"]
        runs_after = [activity for activity in data["activities"]
                      if activity["sport"] == "running"]
        self.assertEqual(runs_after, runs_before)
        self.assertEqual(data["metadata"]["dataset_type"], "recorded-visible-review")
        self.assertTrue(data["metadata"]["cycling_full_route"])
        self.assertNotIn("cycling_full_route", self.dataset["metadata"])
        self.assertEqual(len(data["activities"]), 3)
        self.assertEqual(data["activities"][-1]["id"], self.old_ride["id"])
        self.assertNotIn("visible_only", data["activities"][-1])
        self.assertEqual(model.history[self.old_ride["id"]]["distance_m"],
                         self.full_ride["diagnostics"]["session_distance_m"])
        self.assertEqual(model.history[self.old_ride["id"]]["date"], None)
        self.assertEqual(len(comparative["cycling"]["routes"]),
                         len(self.bundle["activities"][-1]["sections"]))
        self.assertTrue(all(row["visible_only"] for row in runs_after))

    def test_rejects_unrelated_cycling_fit(self):
        for fact in self.full_context:
            fact["lat_lon"] = [45, -70]
        with self.assertRaisesRegex(ValueError, "does not match"):
            combine_protected_runs_and_full_ride(
                self.dataset, self.original, self.full_ride, self.full_context
            )

    def test_raw_fitness_payload_cannot_masquerade_as_masked_review(self):
        changed = deepcopy(self.dataset)
        changed["metadata"]["dataset_type"] = "private-fit-preview"
        with self.assertRaisesRegex(ValueError, "privacy-review"):
            combine_protected_runs_and_full_ride(
                changed, self.original, self.full_ride, self.full_context
            )

    def test_bundle_path_must_remain_in_ignored_review_area(self):
        with TemporaryDirectory() as folder:
            outside = Path(folder) / "routes.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "local artifacts"):
                load_recorded_review(outside)


if __name__ == "__main__":
    unittest.main()
