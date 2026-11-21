import math
import unittest

from analysis_core import Sample, interpolate, process_samples, speed_to_kmh, speed_to_pace, split_times, summarize


def sample(time, distance, speed=4, heart=150, elevation=110):
    return Sample(time, distance, distance, 0, speed, heart, elevation)


class NumericalTests(unittest.TestCase):
    def test_speed_and_pace_reference(self):
        self.assertAlmostEqual(speed_to_kmh(4), 14.4)
        self.assertEqual(speed_to_pace(4), 250)
        self.assertEqual(speed_to_kmh(0), 0)
        self.assertIsNone(speed_to_pace(0))
        for bad in (None, -1, True, math.nan, math.inf):
            for convert in (speed_to_kmh, speed_to_pace):
                with self.subTest(value=bad, conversion=convert.__name__):
                    self.assertIsNone(convert(bad))

    def test_invalid_axes_are_rejected(self):
        for samples, message in (
            ([], "start at zero"),
            ([sample(1, 0)], "start at zero"),
            ([sample(0, 1)], "start at zero"),
            ([sample(0, 0), sample(0, 1)], "strictly increase"),
            ([sample(0, 0), sample(3, 10), sample(2, 20)], "strictly increase"),
            ([sample(0, 0), sample(1, 10), sample(2, 8)], "nondecreasing"),
            ([sample(0, 0), sample(math.inf, 1)], "Non-finite"),
            ([sample(0, 0), Sample(1, 1, math.nan, 0, 1, 100, 20)], "Non-finite"),
        ):
            with self.subTest(samples=samples), self.assertRaisesRegex(ValueError, message):
                process_samples(samples)

    def test_signal_quality_keeps_source_and_masks_derivatives(self):
        records = process_samples([
            sample(0, 0, 0, None, math.nan), sample(1, 4, 72, 292, 120),
            sample(2, 8, None, 150, 122), sample(3, 12, -1, 25, None),
        ])
        self.assertEqual(records[0]["derived"], {"speed_kmh": 0, "pace_s_per_km": None})
        self.assertEqual(records[0]["quality"], {"speed_mps": "valid", "heart_rate_bpm": "missing", "elevation_m": "invalid"})
        self.assertIsNone(records[0]["source"]["elevation_m"])
        self.assertEqual(records[1]["source"]["speed_mps"], 72)
        self.assertEqual(records[1]["quality"]["heart_rate_bpm"], "invalid")
        self.assertEqual([entry["quality"]["speed_mps"] for entry in records[1:]], ["invalid", "missing", "invalid"])
        self.assertTrue(all(entry["derived"]["pace_s_per_km"] is None for entry in records))

    def test_time_and_distance_interpolation_on_adjacent_pairs(self):
        records = process_samples([
            sample(0, 0, 3, 120, 100), sample(100, 400, 5, 140, 120),
            sample(200, 800, 4, None, 100), sample(300, 800, 0, 155, 100),
            sample(400, 1000, 3, 160, 105),
        ])
        expected = {"elapsed_s": 50, "distance_m": 200, "x_m": 200, "y_m": 0,
                    "speed_mps": 4, "heart_rate_bpm": 130, "elevation_m": 110}
        self.assertEqual(interpolate(records, "elapsed_s", 50), expected)
        self.assertEqual(interpolate(records, "distance_m", 200), expected)
        self.assertEqual(interpolate(records, "distance_m", 800)["elapsed_s"], 200)
        self.assertEqual(interpolate(records, "distance_m", 900)["elapsed_s"], 350)
        self.assertEqual(interpolate(records, "elapsed_s", 250)["distance_m"], 800)
        self.assertIsNone(interpolate(records, "elapsed_s", 150)["heart_rate_bpm"])
        self.assertEqual(interpolate(records, "elapsed_s", 100)["heart_rate_bpm"], 140)
        self.assertEqual(interpolate(records, "elapsed_s", 0)["distance_m"], 0)
        self.assertEqual(interpolate(records, "elapsed_s", 400)["distance_m"], 1000)
        for target in (-1, 401, None, math.nan):
            self.assertIsNone(interpolate(records, "elapsed_s", target))
        with self.assertRaises(ValueError):
            interpolate(records, "elevation_m", 100)

    def test_full_and_partial_splits_with_exact_boundary_and_stop(self):
        records = process_samples([sample(time, distance) for time, distance in
                                   [(0, 0), (100, 400), (250, 1000), (280, 1000),
                                    (380, 1500), (580, 2300)]])
        splits = split_times(records)
        self.assertEqual([entry["end_m"] for entry in splits], [1000, 2000, 2300])
        self.assertEqual([entry["duration_s"] for entry in splits], [250, 255, 75])
        self.assertEqual([entry["pace_s_per_km"] for entry in splits], [250, 255, 250])
        self.assertEqual([entry["complete"] for entry in splits], [True, True, False])
        self.assertEqual(len(split_times(records[:3])), 1)
        self.assertEqual(split_times(records[:4])[0]["duration_s"], 250)
        self.assertEqual(summarize(records[:4])["elapsed_s"], 280)
        self.assertEqual(split_times(records[:1]), [])
        self.assertEqual(split_times(records, 3000)[0]["duration_s"], 580)
        with self.assertRaises(ValueError):
            split_times(records, 0)

    def test_time_weighted_summary_and_elevation_gaps(self):
        records = process_samples([
            sample(0, 0, heart=100, elevation=100), sample(10, 40, heart=120, elevation=103),
            sample(20, 80, heart=None, elevation=None), sample(50, 200, heart=160, elevation=110),
            sample(60, 240, heart=180, elevation=108),
        ])
        summary = summarize(records)
        self.assertEqual(summary["distance_m"], 240)
        self.assertEqual(summary["elapsed_s"], 60)
        self.assertAlmostEqual(summary["mean_speed_kmh"], 14.4)
        self.assertEqual(summary["mean_pace_s_per_km"], 250)
        self.assertEqual(summary["mean_heart_rate_bpm"], 140)
        self.assertAlmostEqual(summary["heart_rate_coverage"], 1 / 3)
        self.assertEqual(summary["elevation_gain_m"], 3)
        self.assertEqual(summary["elevation_valid_interval_count"], 2)

    def test_summary_with_no_usable_intervals(self):
        records = process_samples([sample(0, 0, heart=None, elevation=None)])
        summary = summarize(records)
        for key in ("mean_speed_kmh", "mean_pace_s_per_km", "mean_heart_rate_bpm",
                    "heart_rate_coverage", "elevation_gain_m"):
            self.assertIsNone(summary[key])
        stopped = summarize(process_samples([sample(0, 0, 0, None), sample(1, 0, 0, None)]))
        self.assertEqual(stopped["mean_speed_kmh"], 0)
        self.assertIsNone(stopped["mean_pace_s_per_km"])
        self.assertEqual(stopped["heart_rate_coverage"], 0)
