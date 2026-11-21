"""Prepare selected private FIT activities in memory for the loopback dashboard."""

from collections import Counter
import json
from math import cos, radians
from pathlib import Path

from analysis_core import PROCESSING_VERSION, Sample, process_sample, split_times, summarize
from environmental import EARTH_RADIUS_M, geographic_distance
from fit_reader import EVENT, FILE_ID, RECORD, SESSION, TIMESTAMP, FitError, messages
from synthetic_data import UNITS


PRIVATE_ROOT = Path(__file__).resolve().parent / "private-data"
DEGREES_PER_SEMICIRCLE = 180 / 2**31
MAX_GAP_S = 30
TIMER_STOPS = {1, 4, 8, 9}
FIT_UNIX_EPOCH = 631065600


def read_selected_run(path):
    return read_selected_activity(path, 1)


def read_selected_activity(path, sport):
    path = path.resolve()
    if not path.is_relative_to(PRIVATE_ROOT) or path.suffix.lower() != ".fit":
        raise FitError("Select a FIT file inside the ignored private-data directory")
    sessions, samples, events = [], [], []
    activity_file = False
    try:
        for kind, fields in messages(path.read_bytes()):
            if kind == FILE_ID:
                activity_file = fields.get(0) == 4
            elif kind == SESSION:
                sessions.append(fields)
            elif kind == RECORD:
                samples.append(fields)
            elif kind == EVENT and fields.get(0) == 0 and TIMESTAMP in fields:
                events.append((fields[TIMESTAMP], fields.get(1)))
    except OSError:
        raise FitError("Could not read the selected FIT file") from None
    if not activity_file or len(sessions) != 1 or sessions[0].get(5) != sport:
        name = {1: "running", 2: "cycling"}[sport]
        raise FitError(f"The preview requires one {name} session in each selected FIT file")
    return sessions[0], samples, events


def position(fields):
    if 0 not in fields or 1 not in fields:
        return None, "missing"
    lat, lon = (fields[key] * DEGREES_PER_SEMICIRCLE for key in (0, 1))
    if abs(lat) > 90 or abs(lon) > 180:
        return None, "invalid"
    return (lat, lon), "valid"


def pause_windows(events):
    start = None
    pauses = []
    for time, event in sorted(events, key=lambda item: item[0]):
        if event in TIMER_STOPS and start is None:
            start = time
        elif event == 0 and start is not None:
            if time > start:
                pauses.append((start, time))
            start = None
    if start is not None:
        pauses.append((start, float("inf")))
    return pauses


def scale_measurement(fields, primary, divisor, *, alternate=None, offset=0):
    raw = fields.get(primary, fields.get(alternate))
    return raw / divisor - offset if raw is not None else None


def normalize_run(raw, longitude_scale, index, *, environmental=None, cycling=False):
    session, samples, events = raw
    first_time = next((fields[TIMESTAMP] for fields in samples if TIMESTAMP in fields), None)
    if first_time is None:
        raise FitError("Activity has no usable record timestamps")
    session_start = session.get(2)
    use_session_start = session_start is not None and session_start <= first_time
    origin = session_start if use_session_start else first_time
    pauses = pause_windows(events)
    counters = Counter()
    records = []
    last_time = last_position = last_distance = None
    skipped = False
    for fields in samples:
        time = fields.get(TIMESTAMP)
        if time is None or (last_time is not None and time <= last_time):
            counters["missing_timestamps" if time is None else "non_increasing_timestamps"] += 1
            skipped = True
            continue
        point, position_status = position(fields)
        x, y = (longitude_scale * radians(point[1]), EARTH_RADIUS_M * radians(point[0])) if point else (None, None)
        distance = scale_measurement(fields, 5, 100)
        distance_status = "missing" if distance is None else "valid"
        if distance is not None:
            if last_distance is not None and distance < last_distance:
                distance, distance_status = None, "invalid"
            else:
                last_distance = distance

        long_gap = paused = jump = False
        pause_s = 0
        if last_time is not None:
            dt = time - last_time
            long_gap = dt > MAX_GAP_S
            pause_s = sum(max(0, min(time, end) - max(last_time, start)) for start, end in pauses)
            paused = pause_s > 0
            if point is not None and last_position is not None and not (long_gap or paused or skipped):
                displacement = geographic_distance(last_position, point)
                jump = displacement > max(20, (35 if cycling else 15) * dt)
        counters["long_gaps"] += long_gap
        counters["pause_intervals"] += paused
        counters["gps_jumps"] += jump
        sample = Sample(
            time - origin, distance, x, y,
            scale_measurement(fields, 73, 1000, alternate=6), fields.get(3),
            scale_measurement(fields, 78, 5, alternate=2, offset=500),
        )
        record = process_sample(sample, len(records))
        record["quality"].update(position=position_status, distance_m=distance_status)
        record["break_before"] = long_gap or paused or (skipped and bool(records))
        record["route_break_before"] = record["break_before"] or jump
        if environmental is not None:
            environmental.append({
                "utc_s": time + FIT_UNIX_EPOCH, "lat_lon": point,
                "temperature_c": fields.get(13),
                "stationary_pause_s": pause_s if paused and point is not None and point == last_position
                and not skipped else None,
            })
        records.append(record)
        last_time, last_position = time, point
        skipped = False

    if len(records) < 2 or sum(r["quality"]["position"] == "valid" for r in records) < 2:
        raise FitError("Activity has too few timed GPS samples")
    summary = summarize(records)
    for signal in ("position", "distance_m"):
        summary["quality_counts"][signal] = {status: sum(r["quality"][signal] == status for r in records)
                                              for status in ("valid", "missing", "invalid")}
    diagnostics = {
        "session_distance_m": scale_measurement(session, 9, 100),
        "last_sample_distance_m": summary["distance_m"],
        "session_elapsed_s": scale_measurement(session, 7, 1000),
        "session_timer_s": scale_measurement(session, 8, 1000),
        "last_sample_elapsed_s": summary["elapsed_s"],
        "session_heart_rate_bpm": session.get(16),
        "session_ascent_m": session.get(22),
        "elapsed_origin": "FIT session start" if use_session_start else "First valid record",
        **{key: counters[key] for key in ("missing_timestamps", "non_increasing_timestamps",
                                         "long_gaps", "pause_intervals", "gps_jumps")},
    }
    start_elapsed = 0 if use_session_start or records[0]["source"]["distance_m"] == 0 else None
    return {
        "id": "ride" if cycling else f"run-{index + 1}",
        "name": "Ride" if cycling else (f"Run {chr(65 + index)}" if index < 26 else f"Run {index + 1}"),
        "sport": "cycling" if cycling else "running",
        "shared_segment": None, "samples": records, "summary": summary, "diagnostics": diagnostics,
        "splits": split_times(records, start_elapsed_s=start_elapsed),
    }


def build_private_dataset(paths):
    return private_running_inputs(paths, include_context=False)[0]


def build_private_comparison(paths, *, cycling_path=None, observation_path=None):
    dataset, comparative, _ = build_private_portfolio(paths, cycling_path=cycling_path, observation_path=observation_path)
    return dataset, comparative


def cohort_files(selection):
    selection = selection.resolve()
    if not selection.is_relative_to(PRIVATE_ROOT):
        raise FitError("Select a cohort list or directory inside the ignored private-data directory")
    if selection.is_dir():
        paths = sorted(selection.glob("*.fit"))
    else:
        try:
            files = json.loads(selection.read_text(encoding="utf-8-sig"))["files"]
            if not isinstance(files, list) or any(not isinstance(name, str) or Path(name).name != name for name in files):
                raise ValueError
            paths = [selection.parent / name for name in files]
        except (KeyError, ValueError, OSError, TypeError):
            raise FitError("Invalid cohort list; use a files array of local FIT basenames") from None
    if not 1 <= len(paths) <= 16 or len({path.resolve() for path in paths}) != len(paths):
        raise FitError("Select between one and sixteen distinct candidate FIT files")
    return paths


def staged_review_cohort(paths):
    review = PRIVATE_ROOT / "review"
    manifest = review / "cohort" / "selection.json"
    if any(path.resolve().parent == review for path in paths) and manifest.is_file():
        return manifest
    return None


def build_private_portfolio(paths, *, cycling_path=None, observation_path=None, cohort=None):
    from comparative import build_comparative
    from environmental import Sources
    from geography import route_parts
    from portfolio import Portfolio, date_of, history_row, qualifying_match

    dataset, context, scale = private_running_inputs(paths, include_context=True)
    activities = list(dataset["activities"])
    cycling = cycling_context = None
    if cycling_path is not None:
        raw = read_selected_activity(cycling_path, 2)
        cycling_context = []
        cycling = normalize_run(raw, projection_scale([raw]), 0, environmental=cycling_context, cycling=True)
    sources = Sources.load(observation_path, PRIVATE_ROOT) if observation_path else Sources()
    pair = build_comparative(activities, cycling, context, cycling_context, sources)
    counts = None
    if cohort is not None:
        candidates = cohort_files(cohort)
        counts = {"candidates": len(candidates), "accepted": 0}
        anchor = next((route_parts(a, ctx) for a, ctx in zip(activities, context)
                       if 5500 <= (history_row(a, None)["distance_m"] or 0) <= 6500), None)
        starts = {ctx[0]["utc_s"] - a["samples"][0]["source"]["elapsed_s"] for a, ctx in zip(activities, context)}
        for path in candidates:
            facts = []
            try:
                run = normalize_run(read_selected_run(path), scale, len(activities), environmental=facts)
            except FitError:
                continue
            start = facts[0]["utc_s"] - run["samples"][0]["source"]["elapsed_s"]
            distance = history_row(run, None)["distance_m"] or 0
            coverage = run["summary"]["quality_counts"]["position"]["valid"] / len(run["samples"])
            if not (5500 <= distance <= 6500 and coverage >= .9 and start not in starts):
                continue
            parts = route_parts(run, facts)
            if not parts or (anchor and not qualifying_match(anchor, parts)):
                continue
            anchor = anchor or parts
            starts.add(start)
            counts["accepted"] += 1
            activities.append(run)
            context.append(facts)
    if cycling is not None:
        activities.append(cycling)
        context.append(cycling_context)
    dates = [date_of(a, facts) for a, facts in zip(activities, context)]
    portfolio = Portfolio(dataset, activities, context, dates, sources=sources, pair=pair, cohort=counts)
    return dataset, pair, portfolio


def private_running_inputs(paths, *, include_context):
    if not 1 <= len(paths) <= 2 or len({path.resolve() for path in paths}) != len(paths):
        raise FitError("Select one or two distinct FIT files")
    runs = []
    for index, path in enumerate(paths, start=1):
        try:
            runs.append(read_selected_run(path))
        except FitError as error:
            raise FitError(f"Selected file {index}: {error}") from None
    dataset = {
        "metadata": {"dataset_type": "private-fit-preview", "schema_version": "1.0.0",
                     "processing_version": PROCESSING_VERSION, "units": UNITS,
                     "coordinate_system": "North-up equirectangular projection of recorded GPS"},
        "activities": [],
    }
    private_inputs = []
    scale = projection_scale(runs)
    for index, run in enumerate(runs):
        context = [] if include_context else None
        dataset["activities"].append(normalize_run(run, scale, index, environmental=context))
        private_inputs.append(context)
    return dataset, private_inputs, scale


def projection_scale(activities):
    positions = [point for _, samples, _ in activities for fields in samples if (point := position(fields)[0])]
    if not positions:
        raise FitError("No recorded GPS positions are available")
    latitudes, longitudes = zip(*positions)
    if max(longitudes) - min(longitudes) > 180:
        raise FitError("Antimeridian-crossing routes are outside this local preview")
    reference_latitude = (min(latitudes) + max(latitudes)) / 2
    return EARTH_RADIUS_M * cos(radians(reference_latitude))
