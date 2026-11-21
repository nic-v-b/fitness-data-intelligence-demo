"""Mask owner-local tracks, then build an explorer from the separate retained observations."""

import json
from math import asinh, cos, hypot, radians, tan
from pathlib import Path
from random import SystemRandom

from analysis_core import PROCESSING_VERSION, Sample, process_sample, split_times, summarize
from comparative import build_comparative
from environmental import EARTH_RADIUS_M, finite, geographic_distance
from portfolio import Portfolio
from synthetic_data import UNITS


BUNDLE_KIND = "recorded-visible-v1"
REVIEW_ROOT = Path(__file__).resolve().parent / "artifacts"
MIN_RADIUS_M = 1000
EXPERIMENTAL_RADII_M = (500, 750)
MASK_PADDING_M = 200
MIN_PART_M = 250
TIMED_GAP_S = 30


def review_path(path):
    """Resolve owner-review inputs/outputs only within the ignored review area."""
    root = REVIEW_ROOT.resolve()
    target = path.resolve()
    if root != REVIEW_ROOT or not target.is_relative_to(root) or target == root:
        raise ValueError("Use a regular path inside the local artifacts directory")
    return target


def valid_position(point):
    return (isinstance(point, (tuple, list)) and len(point) == 2
            and finite(point[0], -80, 80) and finite(point[1], -180, 180))


def mercator_y(latitude):
    return asinh(tan(radians(latitude)))


def edge_upper_bound(a, b):
    """Upper-bound ground length for both the Mercator and offline rendered lines."""
    dy = max(abs(mercator_y(a[0]) - mercator_y(b[0])), abs(radians(a[0] - b[0])))
    return EARTH_RADIUS_M * hypot(dy, radians(a[1] - b[1]))


def valid_review_radius(radius, experimental=False):
    return (finite(radius, 500, 750) and radius in EXPERIMENTAL_RADII_M if experimental
            else finite(radius, MIN_RADIUS_M, 100_000))


def retain_sections(samples, facts, centres, radius, *, rng=None, experimental=False):
    """Drop all visits to all masked areas, plus extra recorded distance at each cut."""
    if (not valid_review_radius(radius, experimental) or not centres
            or not all(map(valid_position, centres))):
        raise ValueError("Use valid protected endpoints and at least 1,000 m, or opt into a 500 or 750 m experiment")
    rng = rng if rng is not None else SystemRandom()
    limit = radius + MASK_PADDING_M
    sections = []
    piece = []
    previous = previous_distances = None
    for sample, fact in zip(samples, facts, strict=True):
        point = fact["lat_lon"]
        distances = [geographic_distance(point, centre) for centre in centres] if valid_position(point) else []
        safe = bool(distances) and min(distances) > limit
        if piece:
            continuous = safe and not sample.get("route_break_before")
            if continuous:
                bound = edge_upper_bound(previous, point)
                continuous = all((a + b - bound) / 2 > limit for a, b in zip(previous_distances, distances))
            if not continuous:
                add_interior_piece(sections, piece, rng)
                piece = []
        if safe:
            source = sample["source"]
            piece.append((point, source))
        previous, previous_distances = point, distances
    add_interior_piece(sections, piece, rng)
    return sections


def add_interior_piece(sections, piece, rng):
    if len(piece) < 2:
        return
    covered = [0.0]
    for (a, _), (b, _) in zip(piece, piece[1:]):
        covered.append(covered[-1] + geographic_distance(a, b))
    left, right = rng.uniform(300, 650), covered[-1] - rng.uniform(300, 650)
    kept = [(point, source, distance) for (point, source), distance in zip(piece, covered)
            if left <= distance <= right]
    if len(kept) < 2 or kept[-1][2] - kept[0][2] < MIN_PART_M:
        return
    rows = []
    last = kept[0][1]["elapsed_s"]
    for point, source, _ in kept:
        stamp = source["elapsed_s"]
        rows.append([*point, stamp - last, source["speed_mps"], source["heart_rate_bpm"], source["elevation_m"]])
        last = stamp
    sections.append(rows)


def valid_row(row, first):
    return (isinstance(row, list) and len(row) == 6 and valid_position(row[:2])
            and (finite(row[2], 0, 0) if first else finite(row[2], .001, TIMED_GAP_S))
            and all(value is None or finite(value, -1e6, 1e6) for value in row[3:]))


def build_recorded_portfolio(bundle):
    if (not isinstance(bundle, dict) or set(bundle) != {"kind", "activities"}
            or bundle["kind"] != BUNDLE_KIND or not isinstance(bundle["activities"], list)):
        raise ValueError("Expected a retained-observations review bundle")
    entries = bundle["activities"]
    if not 3 <= len(entries) <= 6:
        raise ValueError("Use two to five retained runs and one ride")
    positions = []
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"sport", "sections"}
                or entry["sport"] not in ("running", "cycling") or not isinstance(entry["sections"], list)
                or not entry["sections"]):
            raise ValueError("Invalid retained activity")
        for section in entry["sections"]:
            if (not isinstance(section, list) or len(section) < 2
                    or not all(valid_row(row, i == 0) for i, row in enumerate(section))):
                raise ValueError("Invalid retained section")
            positions.extend(row[:2] for row in section)
    if sum(entry["sport"] == "cycling" for entry in entries) != 1:
        raise ValueError("Expected one retained ride")
    latitudes, longitudes = zip(*positions)
    if max(longitudes) - min(longitudes) > 180:
        raise ValueError("Antimeridian-crossing routes are outside this review")
    origin_lat = (min(latitudes) + max(latitudes)) / 2
    origin_lon = (min(longitudes) + max(longitudes)) / 2
    scale = EARTH_RADIUS_M * cos(radians(origin_lat))
    activities, contexts = [], []
    run_count = 0
    for entry in entries:
        cycling = entry["sport"] == "cycling"
        if not cycling:
            run_count += 1
        activity, context = build_activity(entry, run_count, scale, origin_lat, origin_lon)
        activities.append(activity)
        contexts.append(context)
    dataset = {"metadata": {"dataset_type": "recorded-visible-review", "schema_version": "1.0.0",
                            "processing_version": PROCESSING_VERSION, "units": UNITS,
                            "coordinate_system": "North-up local projection of retained recorded GPS"},
               "activities": activities}
    # The dynamic pair selector aligns whichever retained same-route runs the viewer chooses.
    ride_index = next(i for i, activity in enumerate(activities) if activity["sport"] == "cycling")
    comparative = build_comparative([], activities[ride_index], ride_context=contexts[ride_index])
    model = Portfolio(dataset, activities, contexts, [None] * len(activities), pair=comparative)
    return dataset, comparative, model


def build_activity(entry, run_number, scale, origin_lat, origin_lon):
    records, context = [], []
    distance = timer = 0.0
    for section in entry["sections"]:
        previous = None
        for lat, lon, dt, speed, heart, elevation in section:
            x = scale * radians(lon - origin_lon)
            y = EARTH_RADIUS_M * radians(lat - origin_lat)
            if previous is not None:
                distance += hypot(x - previous[0], y - previous[1])
                timer += dt
            sample = process_sample(Sample(timer, distance, x, y, speed, heart, elevation), len(records))
            sample["break_before"] = sample["route_break_before"] = previous is None and bool(records)
            records.append(sample)
            context.append({"lat_lon": [lat, lon]})
            previous = x, y
    if distance <= 0 or timer <= 0:
        raise ValueError("Retained observations have no timed movement")
    cycling = entry["sport"] == "cycling"
    return ({"id": "recorded-ride-01" if cycling else f"recorded-run-{run_number:02d}",
             "name": "Recorded Ride 01" if cycling else f"Recorded Run {run_number:02d}",
             "sport": entry["sport"], "samples": records, "summary": summarize(records),
             "visible_only": True, "shared_segment": None, "splits": split_times(records)}, context)


def load_recorded_review(path):
    path = review_path(path)
    if path.suffix != ".json" or path.stat().st_size > 8_000_000:
        raise ValueError("Use a bounded JSON review bundle")
    return build_recorded_portfolio(json.loads(path.read_text(encoding="utf-8")))