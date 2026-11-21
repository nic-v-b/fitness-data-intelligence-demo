"""One selected activity at a time, with distance and geometry-based peer context."""

from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from statistics import median, quantiles

from comparative import archived_weather, build_comparative, cycling_analysis, fixture_ride, running_comparison
from environmental import Sources
from geography import match_route, route_parts
from insights import explorer_takeaway
from semantics import MIN_PEERS, climb_state, pace_state, percentile, thermal_state, wind_state, workout_state
from synthetic_data import GENERATION, generate_run, route_section


COMPARABLE_RUN_M = (5500, 6500)
PROFILE_BIN_M = 100


def history_row(activity, activity_date):
    summary, device = activity["summary"], activity.get("diagnostics", {})
    distance = device.get("session_distance_m") or summary["distance_m"]
    duration = device.get("session_timer_s") or (summary["elapsed_s"] if not device else None)
    pace = duration * 1000 / distance if duration and distance else None
    return {"id": activity["id"], "name": activity["name"], "date": activity_date,
            "sport": activity["sport"], "distance_m": distance, "duration_s": duration,
            "pace_s_per_km": pace, "speed_kmh": 3600 / pace if pace else None,
            "heart_bpm": summary["mean_heart_rate_bpm"],
            "heart_coverage": summary["heart_rate_coverage"],
            "ascent_m": device.get("session_ascent_m", summary["elevation_gain_m"])}


def similar_runs(selected, history):
    distance = selected["distance_m"]
    if selected["sport"] != "running" or distance is None:
        return []
    low, high = COMPARABLE_RUN_M if 5500 <= distance <= 6500 else (distance - 500, distance + 500)
    return [row for row in history if row["id"] != selected["id"] and row["sport"] == selected["sport"]
            and row["distance_m"] is not None and low <= row["distance_m"] <= high
            and row["pace_s_per_km"] is not None]


def distribution(values):
    result = {"count": len(values), "median": median(values) if values else None, "band": None}
    if len(values) >= 4:
        q1, _, q3 = quantiles(values, n=4, method="inclusive")
        result["band"] = [q1, q3]
    return result


def similar_context(selected, similar):
    pace = selected["pace_s_per_km"]
    peers = [row["pace_s_per_km"] for row in similar]
    stats = distribution(peers)
    stats["percentile"] = percentile(pace, peers, lower_better=True)
    return stats


def qualifying_match(a_parts, b_parts, *, min_m=3000):
    match = match_route(a_parts, b_parts)
    if not match:
        return None
    _, _, links = match
    shared = links[-1].a_m - links[0].a_m
    smaller = min(sum(p.length for p in parts) for parts in (a_parts, b_parts))
    ratio = (links[-1].b_m - links[0].b_m) / shared
    return match if shared >= max(min_m, .6 * smaller) and .85 <= ratio <= 1.15 else None


def aligned_distance(links, distances, target):
    index = bisect_left(distances, target)
    if index == 0 or distances[index] == target:
        return links[index].b_m
    left, right = links[index - 1:index + 1]
    fraction = (target - left.a_m) / (right.a_m - left.a_m)
    return left.b_m + (right.b_m - left.b_m) * fraction


def same_route_profile(parts, matches):
    if not matches:
        return None
    chosen = max(parts, key=lambda part: sum(match[0] is part for match in matches))
    reference = [(b, links, [link.a_m for link in links])
                 for a, b, links in matches if a is chosen]
    earliest = min(dist[0] for _, _, dist in reference)
    latest = max(dist[-1] for _, _, dist in reference)
    start = int((earliest + PROFILE_BIN_M - 1) // PROFILE_BIN_M) * PROFILE_BIN_M
    offset = sum(part.length for part in parts[:parts.index(chosen)])
    bins = []
    for lo in range(start, int(latest) - PROFILE_BIN_M + 1, PROFILE_BIN_M):
        hi = lo + PROFILE_BIN_M
        peers = []
        for b, links, distances in reference:
            if lo < distances[0] or hi > distances[-1]:
                continue
            b_lo, b_hi = (aligned_distance(links, distances, distance) for distance in (lo, hi))
            if .75 * PROFILE_BIN_M <= b_hi - b_lo <= 1.25 * PROFILE_BIN_M:
                seconds = b.interval(b_lo, b_hi)["moving_s"]
                if seconds > 0:
                    peers.append(10 * seconds)
        seconds = chosen.interval(lo, hi)["moving_s"]
        bins.append({"distance_m": lo + offset + PROFILE_BIN_M / 2, "width_m": PROFILE_BIN_M,
                     "selected": 10 * seconds if seconds > 0 and peers else None, **distribution(peers)})
    return {"bins": bins, "contributing_peers": len(reference), "end_m": offset + latest,
            "start_m": offset + start, "route_distance_m": sum(part.length for part in parts)}


def date_of(activity, context):
    if not context:
        return None
    stamp = context[0]["utc_s"] - activity["samples"][0]["source"]["elapsed_s"]
    return datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()


class Portfolio:
    def __init__(self, dataset, activities, contexts, dates, *, sources=None, pair=None, synthetic=False, cohort=None):
        self.synthetic = synthetic
        self.metadata = dataset["metadata"]
        self.sources = sources or Sources()
        self.activities = {a["id"]: a for a in activities}
        self.contexts = dict(zip(self.activities, contexts))
        self.parts = {key: route_parts(a, self.contexts[key]) for key, a in self.activities.items()}
        self.history = {a["id"]: history_row(a, day) for a, day in zip(activities, dates)}
        self.pair = pair
        self.pair_ids = [a["id"] for a in dataset["activities"][:2]]
        self.cohort = cohort
        self.detail = lru_cache(maxsize=4)(self.detail)

    def conditions(self, key):
        if not self.synthetic:
            return archived_weather(self.activities[key], self.contexts[key], self.sources)
        i = list(self.activities).index(key)
        return {"air_temperature_c": 11 + (i * 3 % 13), "wind_speed_mps": 2 + i % 6 * .65,
                "wind_from_deg": (215 + i * 28) % 360}

    def index(self):
        return {"metadata": self.metadata, "history": list(self.history.values()), "cohort": self.cohort}

    def compare_runs(self, activity_id, peer_id):
        if activity_id not in self.activities or self.activities[activity_id]["sport"] != "running":
            return None
        if peer_id not in self.detail(activity_id)["peer_context"]["peer_ids"]:
            return None
        ids = [activity_id, peer_id]
        # The original fictional pair has its own fixed weather scenario.
        running = running_comparison([self.activities[key] for key in ids], [self.contexts[key] for key in ids],
                                     self.sources, synthetic=False)
        return {"running": running, "run_ids": ids, "synthetic": self.synthetic,
                "methods": self.pair["methods"], "provenance": self.sources.provenance()}

    def detail(self, activity_id):
        activity = self.activities[activity_id]
        facts = self.contexts[activity_id]
        selected = self.history[activity_id]
        weather = archived_weather(activity, facts, self.sources)
        result = {"activity": activity, "history": selected, "activity_weather": weather,
                  "weather_provenance": self.sources.provenance()["activity_weather"] if weather else None,
                  "positions": [sample["lat_lon"] for sample in facts] if facts else None}
        others = [row for row in self.history.values() if row["id"] != activity_id and row["sport"] == activity["sport"]]
        if activity["sport"] == "cycling":
            result["cycling"] = cycling_analysis(activity, facts, self.sources, self.synthetic)
            result["methods"] = self.pair["methods"]
            result["provenance"] = self.pair["provenance"]
            if self.synthetic and result["cycling"]["available"]:
                metrics = result["cycling"]["environment"]
                result["fictional_conditions"] = {"air_temperature_c": metrics["air_temperature_c"],
                                                  "wind_speed_mps": metrics["wind_speed_mps"], "wind_from_deg": 270}
            distance = selected["distance_m"]
            peers = [row for row in others if distance and row["distance_m"] and
                     abs(row["distance_m"] - distance) <= max(5000, .15 * distance)]
            result["semantic"] = self.activity_semantics(result, peers, others)
            result["takeaway"] = explorer_takeaway(result)
            return result
        similar = similar_runs(selected, self.history.values())
        parts = self.parts[activity_id]
        visible = activity.get("visible_only")
        matches = [(peer, match) for peer in (others if visible else similar)
                   if (match := qualifying_match(parts, self.parts[peer["id"]], min_m=1000 if visible else 3000))]
        result["peer_context"] = {"similar": similar_context(selected, similar),
                                  "same_route": similar_context(selected, [peer for peer, _ in matches]),
                                  "profile": same_route_profile(parts, [match for _, match in matches]),
                                  "peer_ids": [peer["id"] for peer, _ in matches]}
        temps = [part.interval(0, part.length) for part in parts]
        temp_duration = sum(part["device_temp_s"] for part in temps)
        moving = sum(part["moving_s"] for part in temps)
        result["device_temperature_c"] = sum(part["device_temp_integral"] for part in temps) / temp_duration if temp_duration else None
        result["device_temperature_coverage"] = temp_duration / moving if moving else 0
        if self.pair and activity_id in self.pair_ids and self.pair["running"]["available"]:
            result["pair"] = {name: self.pair[name] for name in ("running", "provenance", "methods")}
            result["pair"]["run_ids"] = self.pair_ids
        if self.synthetic:
            result["fictional_conditions"] = self.conditions(activity_id)
        peer_weather = [self.conditions(peer["id"]) for peer, _ in matches]
        result["peer_weather"] = {field: distribution([row[field] for row in peer_weather
                                                       if row and row[field] is not None])
                                  for field in ("air_temperature_c", "wind_speed_mps")}
        same = [peer for peer, _ in matches]
        result["semantic"] = self.activity_semantics(result, similar, others, same)
        pair_index = self.pair_ids.index(activity_id) if result.get("pair") else None
        result["takeaway"] = explorer_takeaway(result, pair_index)
        return result

    def activity_semantics(self, result, similar, others, same=()):
        selected = result["history"]
        weather = result["activity_weather"] or result.get("fictional_conditions", {})
        origin = "Fictional air temperature" if self.synthetic else "Whole-activity historical weather estimate"
        climb = climb_state(selected, similar)
        ride = result.get("cycling", {})
        bins = ride.get("bins", [])
        resolved = wind_state(bins, whole_wind=weather.get("wind_speed_mps"))
        if ride.get("activity_weather") and resolved["sufficiency"] == "insufficient":
            archived = wind_state(bins, archived=True, whole_wind=weather.get("wind_speed_mps"))
            if archived["sufficiency"] == "supported":
                resolved = archived
        out = {"climb": climb, "thermal": thermal_state(weather.get("air_temperature_c"), origin), "wind": resolved,
               "workout": workout_state(selected, same if len(same) >= MIN_PEERS else similar, others, climb)}
        if result.get("peer_context"):
            refs = result["peer_context"]
            out.update({name: pace_state(selected["pace_s_per_km"], refs[key]["median"], refs[key]["count"], basis)
                        for name, key, basis in (("similar_pace", "similar", "similar-distance"),
                                                 ("route_pace", "same_route", "same-route"))})
        return out


def public_portfolio(dataset):
    shared = GENERATION["shared_segment"]
    count = GENERATION["subdivisions_per_curve"]
    def scale(point):
        return tuple(value * 1.145 for value in point)

    geometry = [scale(point) for point in route_section(shared["start_xy_m"], shared["curves"], count)]
    activities = list(dataset["activities"])
    for i in range(12):
        template = GENERATION["runs"][i % 2]
        settings = {**template, "id": f"ridge-{i + 1}", "name": f"6 km Demo Run {i + 1:02d}",
                    "seed": 24800 + i, "base_speed_mps": 3.05 + .049 * i, "phase": i * .31,
                    "base_heart_rate_bpm": 151 - (i % 5), "signal_overrides": {}}
        settings["start_xy_m"] = scale(template["start_xy_m"])
        for name in ("entry_curves", "exit_curves"):
            settings[name] = [tuple(scale(point) for point in curve) for curve in template[name]]
        run = generate_run(settings, geometry, count)
        if i >= 10:
            run["shared_segment"] = None
            for sample in run["samples"]:
                sample["source"]["x_m"] += 3800
        activities.append(run)
    dates = ["2026-08-05", "2026-08-08", *[
        (date(2026, 9, 24) - timedelta(days=3 * i)).isoformat() for i in range(len(activities) - 2)
    ]]
    pair = build_comparative(dataset["activities"], synthetic=True)
    return Portfolio(dataset, [*activities, fixture_ride()], [None] * (len(activities) + 1),
                     [*dates, "2026-09-19"], pair=pair, synthetic=True)
