"""Generate two repeatable activities on a fictional Cartesian route network."""

from math import hypot, sin
from random import Random

from analysis_core import ASSUMPTIONS, PROCESSING_VERSION, Sample, process_samples, split_times, summarize


GENERATION = {
    "version": "1.0.0",
    "subdivisions_per_curve": 18,
    "shared_segment": {
        "id": "ridge-traverse",
        "name": "Ridge traverse",
        "start_xy_m": (470, 330),
        "curves": (
            ((620, 320), (810, 390), (770, 560)),
            ((730, 730), (455, 765), (435, 973)),
            ((410, 1235), (700, 1515), (1005, 1540)),
            ((1190, 1555), (1500, 1480), (1535, 1300)),
            ((1570, 1120), (1260, 1050), (1370, 856)),
            ((1445, 724), (1690, 712), (1780, 812)),
            ((1860, 900), (1885, 1000), (2010, 965)),
        ),
    },
    "runs": (
        {
            "id": "west-run", "name": "5 km Demo Run 01", "seed": 24031,
            "base_speed_mps": 3.18, "base_heart_rate_bpm": 146, "phase": 0.0,
            "start_xy_m": (60, 505),
            "entry_curves": (
                ((180, 500), (167, 272), (305, 280)),
                ((375, 284), (388, 336), (470, 330)),
            ),
            "exit_curves": (
                ((2115, 935), (2180, 861), (2180, 715)),
                ((2180, 525), (2000, 434), (1840, 405)),
            ),
            "signal_overrides": {
                "heart_rate_bpm": {58: None, 59: None, 60: None, 112: 292},
                "speed_mps": {94: None, 145: 72},
                "elevation_m": {128: None},
            },
        },
        {
            "id": "east-run", "name": "5 km Demo Run 02", "seed": 24032,
            "base_speed_mps": 3.36, "base_heart_rate_bpm": 151, "phase": 1.1,
            "start_xy_m": (55, 993),
            "entry_curves": (
                ((140, 935), (260, 918), (261, 772)),
                ((262, 537), (270, 339), (470, 330)),
            ),
            "exit_curves": (
                ((2120, 934), (2210, 1037), (2240, 1135)),
                ((2280, 1260), (2160, 1370), (2080, 1420)),
            ),
            "signal_overrides": {
                "heart_rate_bpm": {75: None, 76: None, 119: 16},
                "speed_mps": {44: None, 45: None, 146: -1.5},
                "elevation_m": {102: None},
            },
        },
    ),
}

UNITS = {
    "elapsed_s": "s", "distance_m": "m", "x_m": "m east", "y_m": "m north",
    "speed_mps": "m/s", "speed_kmh": "km/h", "pace_s_per_km": "s/km",
    "heart_rate_bpm": "bpm", "elevation_m": "m", "duration_s": "s", "start_m": "m", "end_m": "m",
    "mean_speed_kmh": "km/h", "mean_pace_s_per_km": "s/km", "mean_heart_rate_bpm": "bpm",
    "heart_rate_coverage": "fraction of elapsed time", "elevation_gain_m": "m",
}


def route_section(start, curves, subdivisions):
    """Sample each cubic Bézier curve at equal parameter increments."""
    points = [start]
    for control_a, control_b, end in curves:
        for step in range(1, subdivisions + 1):
            t = step / subdivisions
            weights = ((1 - t)**3, 3 * (1 - t)**2 * t, 3 * (1 - t) * t**2, t**3)
            points.append(tuple(round(sum(weight * coordinate for weight, coordinate in zip(weights, axis)), 6)
                                for axis in zip(start, control_a, control_b, end)))
        start = end
    return points


def generate_run(config, shared_points, subdivisions):
    entry = route_section(config["start_xy_m"], config["entry_curves"], subdivisions)
    exit_route = route_section(shared_points[-1], config["exit_curves"], subdivisions)
    points = entry + shared_points[1:] + exit_route[1:]
    rng = Random(config["seed"])
    distance = elapsed = 0.0
    previous_speed = config["base_speed_mps"]
    previous_x, previous_y = points[0]
    samples = []
    for index, (x, y) in enumerate(points):
        phase = config["phase"]
        speed = (config["base_speed_mps"] + 0.31 * sin(index / 10 + phase)
                 + 0.13 * sin(index / 3.3) + rng.uniform(-0.09, 0.09))
        step_m = hypot(x - previous_x, y - previous_y)
        distance += step_m
        elapsed += step_m / ((speed + previous_speed) / 2)
        heart = (config["base_heart_rate_bpm"] - 12 / (1 + index / 13) + 0.060 * index
                 + 4.5 * sin(index / 13 + phase) + 2.4 * sin(index / 5.5) + rng.uniform(-2, 2))
        elevation = 109 + 0.025 * y + 0.008 * x + 9 * sin(x / 380) - 5 * sin(y / 275)
        signals = {"speed_mps": round(speed, 3), "heart_rate_bpm": round(heart),
                   "elevation_m": round(elevation, 2)}
        for name, overrides in config["signal_overrides"].items():
            if index in overrides:
                signals[name] = overrides[index]
        samples.append(Sample(round(elapsed, 6), round(distance, 6), x, y, **signals))
        previous_speed, previous_x, previous_y = speed, x, y

    records = process_samples(samples)
    start_index = len(entry) - 1
    end_index = start_index + len(shared_points) - 1
    return {
        "id": config["id"], "name": config["name"], "sport": "running",
        "shared_segment": {"id": GENERATION["shared_segment"]["id"],
                           "start_index": start_index, "end_index": end_index},
        "samples": records,
        "summary": summarize(records),
        "splits": split_times(records),
    }


def build_dataset():
    shared = GENERATION["shared_segment"]
    subdivisions = GENERATION["subdivisions_per_curve"]
    points = route_section(shared["start_xy_m"], shared["curves"], subdivisions)
    return {
        "metadata": {
            "schema_version": "1.0.0", "processing_version": PROCESSING_VERSION,
            "dataset_type": "synthetic", "dataset_id": "ridge-traverse-v1",
            "coordinate_system": "fictional Cartesian east/north metres",
            "generation": GENERATION, "units": UNITS, "assumptions": ASSUMPTIONS,
        },
        "activities": [generate_run(config, points, subdivisions) for config in GENERATION["runs"]],
    }
