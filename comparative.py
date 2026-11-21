"""Assemble matched-running and directional cycling analyses for the local UI."""

from math import hypot, pi, sin
from statistics import fmean, median

from analysis_core import Sample, process_samples, split_times, summarize
from environmental import Sources, heading_deg, wind_components
from geography import (MATCH_MIN_M, MATCH_STEP_M, MATCH_TOLERANCE_M, MAX_HEADING_DIFFERENCE_DEG,
                       match_route, route_parts)


RUN_BIN_M = 50
RIDE_BIN_M = 100
GRADE_BASELINE_M = 100
CLIMB_BASELINE_M = 500


def grade_percent(start, end, distance):
    return 100 * (end - start) / distance if start is not None and end is not None and distance > 0 else None


def summary_metrics(totals, distance):
    moving = totals["moving_s"]
    heart = totals["heart_s"]
    temp = totals["device_temp_s"]
    return {
        "moving_s": moving, "elapsed_s": totals["elapsed_s"],
        "pace_s_per_km": moving * 1000 / distance if moving > 0 and distance > 0 else None,
        "mean_heart_bpm": totals["heart_integral"] / heart if heart else None,
        "heart_coverage": heart / moving if moving else 0,
        "device_temperature_c": totals["device_temp_integral"] / temp if temp else None,
        "device_temperature_coverage": temp / moving if moving else 0,
    }


def location_values(part, distance, sources, fixture_index=None):
    east, north = part.direction(distance)
    heading = heading_deg(east, north)
    lat_lon, time = part.observation_position(distance)
    weather = sources.weather_at(lat_lon, time)
    if fixture_index is not None:
        weather = {
            "air_temperature_c": (13 if fixture_index == 0 else 20) + sin(distance / 4300),
            "wind_speed_mps": (3.0, 5.5, 6.3)[fixture_index] + 0.7 * sin(distance / 2400),
            "wind_from_deg": (225, 75, 270)[fixture_index],
        }
    wind, direction = weather.get("wind_speed_mps"), weather.get("wind_from_deg")
    headwind, crosswind = wind_components(wind, direction, heading)
    return {"heading_deg": heading, "air_temperature_c": weather.get("air_temperature_c"),
            "wind_speed_mps": wind, "wind_from_deg": direction, "headwind_mps": headwind,
            "crosswind_mps": crosswind, "terrain_m": sources.terrain_at(lat_lon)}


def environmental_summary(bins, distance):
    result = {}
    for field in ("air_temperature_c", "wind_speed_mps", "headwind_mps", "terrain_m"):
        usable = [(row["width_m"], row[field]) for row in bins if row[field] is not None]
        covered = sum(width for width, _ in usable)
        result[field] = sum(width * value for width, value in usable) / covered if covered else None
        result[field + "_coverage"] = covered / distance if distance else 0
    return result


def archived_weather(activity, context, sources):
    if sources.activity_weather is None or not context or context[0].get("utc_s") is None:
        return None
    start_utc = context[0]["utc_s"] - activity["samples"][0]["source"]["elapsed_s"]
    return sources.activity_weather_at(start_utc)


def running_comparison(runs, context, sources, synthetic):
    if len(runs) != 2:
        return {"available": False, "message": "Select two running recordings to compare shared ground."}
    a_parts, b_parts = [route_parts(run, facts) for run, facts in zip(runs, context)]
    matched = match_route(a_parts, b_parts)
    if not matched:
        return {"available": False, "message": "These routes have no qualifying continuous same-direction segment."}
    a, b, links = matched
    a_start, b_start = links[0].a_m, links[0].b_m
    a_end, b_end = links[-1].a_m, links[-1].b_m
    shared_m = a_end - a_start
    width_steps = RUN_BIN_M // MATCH_STEP_M
    bins = []
    for start in range(0, len(links) - 1, width_steps):
        finish = min(start + width_steps, len(links) - 1)
        left, right = links[start], links[finish]
        width = right.a_m - left.a_m
        midpoint = (left.a_m + right.a_m) / 2
        lower = start + (finish - start) // 2
        fraction = (midpoint - links[lower].a_m) / MATCH_STEP_M
        b_midpoint = links[lower].b_m + fraction * (links[lower + 1].b_m - links[lower].b_m)
        row = {"distance_m": midpoint - a_start, "width_m": width, "values": []}
        for index, (part, lo, centre, hi) in enumerate(((a, left.a_m, midpoint, right.a_m),
                                                        (b, left.b_m, b_midpoint, right.b_m))):
            metrics = summary_metrics(part.interval(lo, hi), width)
            if width < 40 or not .75 * width <= hi - lo <= 1.25 * width:
                metrics["pace_s_per_km"] = None
            row["values"].append({
                **metrics,
                **location_values(part, centre, sources, index if synthetic else None),
                "point": part.point(centre), "width_m": width,
            })
        bins.append(row)
    summaries = []
    for i, (run, part, start, end) in enumerate(zip(runs, (a, b), (a_start, b_start), (a_end, b_end))):
        summaries.append({
            "name": run["name"], "gps_distance_m": end - start,
            "activity_weather": archived_weather(run, context[i], sources),
            **summary_metrics(part.interval(start, end), shared_m),
            **environmental_summary([row["values"][i] for row in bins], shared_m),
        })
    pace_a, pace_b = [summary["pace_s_per_km"] for summary in summaries]
    visible = all(run.get("visible_only") for run in runs)
    shared = [[link.a_m - a_start, *a.point(link.a_m)] for link in links]
    if visible:
        # Keep the recorded vertices at corners so the display never shortcuts a retained edge.
        shared = [[0, *a.point(a_start)], *[[distance - a_start, *point]
                  for distance, point in zip(a.distances, a.points) if a_start < distance < a_end],
                  [shared_m, *a.point(a_end)]]
    return {
        "available": True, "distance_m": shared_m, "runs": summaries, "bins": bins,
        "pace_change_fraction": (pace_b - pace_a) / pace_a if pace_a and pace_b else None,
        "rms_separation_m": (fmean(link.separation_m**2 for link in links))**.5,
        "max_separation_m": max(link.separation_m for link in links),
        "routes": [[part.trace(None if visible else 20) for part in parts] for parts in (a_parts, b_parts)],
        "shared": shared,
    }


def strongest_climb(bins):
    """Find the steepest continuous 500 m section on the full recorded grade bins."""
    size = CLIMB_BASELINE_M // RIDE_BIN_M
    best = None
    for i in range(len(bins) - size + 1):
        section = bins[i:i + size]
        if any(row["break_before"] for row in section[1:]) or any(
            row["width_m"] != RIDE_BIN_M or row["recorded_grade_pct"] is None or not row["speed_kmh"]
            for row in section
        ):
            continue
        grade = fmean(row["recorded_grade_pct"] for row in section)
        if grade > 0 and (best is None or grade > best["grade_pct"]):
            moving = sum(row["width_m"] * 3.6 / row["speed_kmh"] for row in section)
            best = {"distance_m": section[size // 2]["distance_m"], "grade_pct": grade,
                    "speed_kmh": CLIMB_BASELINE_M * 3.6 / moving, "length_m": CLIMB_BASELINE_M}
    return best


def cycling_analysis(ride, context, sources, synthetic):
    if ride is None:
        return {"available": False, "message": "Stage a cycling FIT to inspect terrain and speed. Local wind observations can be loaded alongside it."}
    parts = route_parts(ride, context)
    if not parts:
        return {"available": False, "message": "The selected ride has no continuous GPS edges for this analysis."}
    offset = moving_s = device_temp_s = device_temp_integral = 0.0
    routes, bins = [], []
    half = GRADE_BASELINE_M / 2
    activity_weather = archived_weather(ride, context, sources)
    for part in parts:
        routes.append(part.trace(None if ride.get("visible_only") else 25, offset))
        for start in range(0, int(part.length) + 1, RIDE_BIN_M):
            end = min(start + RIDE_BIN_M, part.length)
            if end <= start:
                continue
            middle = (start + end) / 2
            totals = part.interval(start, end)
            moving_s += totals["moving_s"]
            device_temp_s += totals["device_temp_s"]
            device_temp_integral += totals["device_temp_integral"]
            weather = location_values(part, middle, sources, 2 if synthetic else None)
            reference_headwind, reference_crosswind = wind_components(
                activity_weather["wind_speed_mps"], activity_weather["wind_from_deg"], weather["heading_deg"]
            ) if activity_weather else (None, None)
            record_grade = terrain_grade = None
            if middle >= half and middle + half <= part.length:
                left, right = middle - half, middle + half
                record_grade = grade_percent(part.value(left, "elevation_m"), part.value(right, "elevation_m"),
                                             GRADE_BASELINE_M)
                if weather["terrain_m"] is not None:
                    elevations = [sources.terrain_at(part.observation_position(left + step)[0])
                                  for step in range(0, GRADE_BASELINE_M + 1, 25)]
                    if all(value is not None for value in elevations):
                        terrain_grade = grade_percent(elevations[0], elevations[-1], GRADE_BASELINE_M)
            bins.append({
                "distance_m": offset + middle, "width_m": end - start, "point": part.point(middle),
                "elapsed_s": part.elapsed_at(middle),
                "break_before": start == 0, "elevation_m": part.value(middle, "elevation_m"),
                "recorded_grade_pct": record_grade, "terrain_grade_pct": terrain_grade,
                "speed_kmh": (end - start) * 3.6 / totals["moving_s"] if totals["moving_s"] > 0 else None,
                "reference_headwind_mps": reference_headwind, "reference_crosswind_mps": reference_crosswind,
                **weather,
            })
        offset += part.length
    for i, row in enumerate(bins):
        nearby = bins[i - 1:i + 2] if 0 < i < len(bins) - 1 else ()
        grades = [sample["recorded_grade_pct"] for sample in nearby]
        row["recorded_grade_display_pct"] = (
            median(grades) if grades and None not in grades and not any(sample["break_before"] for sample in nearby[1:])
            else row["recorded_grade_pct"]
        )
    return {"available": True, "name": ride["name"], "distance_m": offset,
            "recorded_distance_m": ride.get("summary", {}).get("distance_m"),
            "recorded_ascent_m": ride.get("diagnostics", {}).get("session_ascent_m"),
            "activity_weather": activity_weather, "strongest_climb": strongest_climb(bins),
            "device_temperature_c": device_temp_integral / device_temp_s if device_temp_s else None,
            "device_temperature_coverage": device_temp_s / moving_s if moving_s else 0,
            "routes": routes, "bins": bins, "environment": environmental_summary(bins, offset)}


def fixture_ride():
    """Fictional terrain and motion chosen to exercise the complete interaction."""
    points = []
    distance = elapsed = 0.0
    for index in range(601):
        angle = pi * index / 300
        x = 6600 * sin(angle) + 1200 * sin(3 * angle)
        y = 4000 * sin(angle - pi / 2) + 500 * sin(4 * angle)
        z = 85 + 29 * sin(3 * angle) + 68 * sin(angle)**2 + 12 * sin(11 * angle)
        speed = 8.4
        if points:
            last = points[-1]
            step = hypot(x - last.x_m, y - last.y_m)
            distance += step
            speed = max(3.5, min(13, 8.4 - 90 * (z - last.elevation_m) / step + sin(5 * angle)))
            elapsed += step / speed
        points.append(Sample(elapsed, distance, x, y, speed, 139 + 9 * sin(8 * angle), z))
    records = process_samples(points)
    return {"id": "foothills", "sport": "cycling", "name": "35 km Demo Ride 01", "samples": records,
            "shared_segment": None, "summary": summarize(records), "splits": split_times(records)}


def build_comparative(runs, ride=None, context=None, ride_context=None, sources=None, *, synthetic=False):
    sources = sources or Sources()
    provenance = sources.provenance()
    if synthetic:
        ride = fixture_ride()
        provenance["weather"] = {
            "provider": "Deterministic fixture", "product": "Fictional weather fields",
            "source_kind": "synthetic", "resolution": "Distance-varying scenario values",
            "reference": "comparative.py",
        }
    return {
        "schema_version": 1, "synthetic": synthetic, "provenance": provenance,
        "methods": {"match_step_m": MATCH_STEP_M, "match_tolerance_m": MATCH_TOLERANCE_M,
                    "match_min_m": MATCH_MIN_M, "max_heading_difference_deg": MAX_HEADING_DIFFERENCE_DEG,
                    "grade_baseline_m": GRADE_BASELINE_M, "ride_bin_m": RIDE_BIN_M, "run_bin_m": RUN_BIN_M},
        "running": running_comparison(runs, context or [None] * len(runs), sources, synthetic),
        "cycling": cycling_analysis(ride, ride_context, sources, synthetic),
    }
