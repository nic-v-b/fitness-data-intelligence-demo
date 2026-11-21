"""Validation and numerical reductions for local activity samples."""

from bisect import bisect_left
from dataclasses import dataclass
from math import isfinite
from statistics import fmean


PROCESSING_VERSION = "1.0.0"
SIGNAL_LIMITS = {"speed_mps": (0, 45), "heart_rate_bpm": (25, 240)}
SIGNALS = ("speed_mps", "heart_rate_bpm", "elevation_m")
AXES = ("elapsed_s", "distance_m", "x_m", "y_m")
ASSUMPTIONS = {
    "axes": "Elapsed time starts at zero and strictly increases. Distance starts at zero and never decreases.",
    "geometry": "Fictional Cartesian east/north axes in metres. Distance is accumulated along the sampled 2D polyline.",
    "screening": "Speed outside 0–45 m/s and heart rate outside 25–240 bpm are invalid. Elevation must be finite.",
    "average_speed": "Total distance divided by elapsed time, including any stops.",
    "average_heart_rate": "Time-weighted trapezoidal mean over intervals with two valid endpoints. Coverage uses total elapsed time.",
    "elevation_gain": "Sum of positive elevation changes on adjacent valid pairs, without smoothing or gap filling.",
    "splits": "1 km by default. Boundary times use linear distance interpolation and the first arrival at an exact distance. A trailing split includes any time after the last full boundary. Stops after an exact finish boundary count in the activity total only.",
    "interpolation": "Linear within an adjacent pair. A signal is null when either endpoint is unusable. Exact samples retain their own values.",
}


@dataclass(frozen=True, slots=True)
class Sample:
    elapsed_s: float
    distance_m: float | None
    x_m: float | None
    y_m: float | None
    speed_mps: float | None
    heart_rate_bpm: float | None
    elevation_m: float | None


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def speed_to_kmh(speed_mps):
    return speed_mps * 3.6 if finite(speed_mps) and speed_mps >= 0 else None


def speed_to_pace(speed_mps):
    return 1000 / speed_mps if finite(speed_mps) and speed_mps > 0 else None


def validate_axes(samples):
    if not samples or samples[0].elapsed_s != 0 or samples[0].distance_m != 0:
        raise ValueError("Samples must start at zero elapsed time and distance")
    previous_time = previous_distance = -1
    for index, sample in enumerate(samples):
        if not all(finite(getattr(sample, name)) for name in AXES):
            raise ValueError(f"Non-finite axis or route coordinate at sample {index}")
        if sample.elapsed_s <= previous_time:
            raise ValueError(f"Elapsed time must strictly increase at sample {index}")
        if sample.distance_m < previous_distance:
            raise ValueError(f"Distance must be nondecreasing at sample {index}")
        previous_time, previous_distance = sample.elapsed_s, sample.distance_m


def signal_status(name, value):
    if value is None:
        return "missing"
    if not finite(value):
        return "invalid"
    if name in SIGNAL_LIMITS:
        lower, upper = SIGNAL_LIMITS[name]
        if not lower <= value <= upper:
            return "invalid"
    return "valid"


def process_samples(samples):
    validate_axes(samples)
    return [process_sample(sample, index) for index, sample in enumerate(samples)]


def process_sample(sample, index):
    """Screen optional signals after the caller has checked the activity axes."""
    source = {name: getattr(sample, name) for name in AXES + SIGNALS}
    quality = {name: signal_status(name, source[name]) for name in SIGNALS}
    speed = source["speed_mps"] if quality["speed_mps"] == "valid" else None
    # JSON has no portable representation for NaN or infinity. Keep their invalid flags.
    for name in SIGNALS:
        if not finite(source[name]):
            source[name] = None
    return {
        "index": index,
        "source": source,
        "derived": {"speed_kmh": speed_to_kmh(speed), "pace_s_per_km": speed_to_pace(speed)},
        "quality": quality,
    }


def valid_value(record, name):
    return record["source"][name] if record["quality"][name] == "valid" else None


def interpolate(records, axis, target):
    """Find an exact record or interpolate adjacent samples on a validated axis."""
    if axis not in ("elapsed_s", "distance_m"):
        raise ValueError("Interpolation requires elapsed_s or distance_m")
    if not records or not finite(target):
        return None
    right = bisect_left(records, target, key=lambda record: record["source"][axis])
    if right == len(records):
        return None
    end = records[right]
    if end["source"][axis] == target:
        return {**{name: end["source"][name] for name in AXES},
                **{name: valid_value(end, name) for name in SIGNALS}}
    if right == 0:
        return None
    start = records[right - 1]
    if end.get("break_before") or end["index"] != start["index"] + 1:
        return None
    fraction = (target - start["source"][axis]) / (end["source"][axis] - start["source"][axis])
    values = {}
    for name in AXES + SIGNALS:
        a, b = (valid_value(record, name) if name in SIGNALS else record["source"][name]
                for record in (start, end))
        values[name] = a + fraction * (b - a) if a is not None and b is not None else None
    values[axis] = target
    return values


def split_times(records, split_m=1000, *, start_elapsed_s=0):
    if not finite(split_m) or split_m <= 0:
        raise ValueError("Split length must be positive and finite")
    distance_records = [record for record in records if record["source"]["distance_m"] is not None]
    if not distance_records:
        return []
    finish_m = distance_records[-1]["source"]["distance_m"]
    splits = []
    start_m, start_s = 0, start_elapsed_s
    while start_m < finish_m:
        boundary = (len(splits) + 1) * split_m
        complete = boundary <= finish_m
        end_m = boundary if complete else finish_m
        end = interpolate(distance_records, "distance_m", boundary) if complete else records[-1]["source"]
        end_s = end["elapsed_s"] if end is not None and end["distance_m"] is not None else None
        distance = end_m - start_m
        duration = end_s - start_s if end_s is not None and start_s is not None else None
        splits.append({
            "number": len(splits) + 1,
            "start_m": start_m,
            "end_m": end_m,
            "distance_m": distance,
            "duration_s": duration,
            "pace_s_per_km": duration * (1000 / distance) if duration is not None else None,
            "complete": complete,
        })
        start_m, start_s = end_m, end_s
    return splits


def summarize(records):
    finish = records[-1]["source"]
    elapsed, distance = finish["elapsed_s"], finish["distance_m"]
    speed = distance / elapsed if elapsed > 0 and distance is not None else None
    heart_integral = heart_duration = rise = 0.0
    elevation_pairs = 0
    for a, b in zip(records, records[1:]):
        if b.get("break_before"):
            continue
        dt = b["source"]["elapsed_s"] - a["source"]["elapsed_s"]
        heart_a, heart_b = (valid_value(record, "heart_rate_bpm") for record in (a, b))
        if heart_a is not None and heart_b is not None:
            heart_integral += fmean((heart_a, heart_b)) * dt
            heart_duration += dt
        elev_a, elev_b = (valid_value(record, "elevation_m") for record in (a, b))
        if elev_a is not None and elev_b is not None:
            rise += max(0, elev_b - elev_a)
            elevation_pairs += 1
    return {
        "distance_m": distance,
        "elapsed_s": elapsed,
        "mean_speed_kmh": speed_to_kmh(speed),
        "mean_pace_s_per_km": speed_to_pace(speed),
        "mean_heart_rate_bpm": heart_integral / heart_duration if heart_duration else None,
        "heart_rate_coverage": heart_duration / elapsed if elapsed else None,
        "elevation_gain_m": rise if elevation_pairs else None,
        "elevation_valid_interval_count": elevation_pairs,
        "sample_count": len(records),
        "quality_counts": {
            name: {status: sum(record["quality"][name] == status for record in records)
                   for status in ("valid", "missing", "invalid")}
            for name in SIGNALS
        },
    }
