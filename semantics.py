"""Shared demonstration classifications independent of the rendered interface."""

from math import isfinite
from statistics import median


MIN_PEERS = 5
MIN_PERIOD = 2
MIN_DAILY_WINDOWS = (5, 14)
MIN_HEART_COVERAGE = .80
READINESS_BANDS = ((40, "low", "Low readiness", "negative"),
                   (60, "reduced", "Reduced readiness", "caution"),
                   (80, "moderate", "Moderate readiness", "neutral"))
LOAD_BANDS = (.8, 1.2, 1.5)
PACE_BANDS = (2, 5)
CLIMB_BANDS = (25, 75, 90)
THERMAL_BANDS = (10, 20, 25, 30)
WIND_BANDS = (2, 4)
TREND_TOLERANCES = {"benchmark": 2, "vo2max": 1, "hrv": 2, "resting_hr": 2, "sleep": 30, "consistency": 1}
LONG_DISTANCE_RATIO = 1.5
LONG_DURATION_S = 3600
WORKOUT_HR_BANDS = (4, 6, 7)
PLAN_READINESS_GUARD = 72


def valid(value, minimum=None):
    return type(value) in (int, float) and isfinite(value) and (minimum is None or value >= minimum)


def state(metric, value, unit, category, label, tone, *, reference=None, evidence=None,
          sufficiency="supported", limitation=None, provenance=None):
    return {"metric": metric, "value": value, "unit": unit, "category": category, "label": label,
            "tone": tone, "reference": reference, "evidence": evidence or {}, "sufficiency": sufficiency,
            "limitation": limitation, "provenance": provenance}


def unavailable(metric, value, unit, label, limitation, **context):
    return state(metric, value, unit, "unavailable", label, "unavailable", sufficiency="insufficient",
                 limitation=limitation, **context)


def readiness_state(score, components):
    limits = "Illustrative composite. The display bands are demonstration defaults."
    names = {"HRV", "Resting heart rate", "Sleep duration", "Training load"}
    if (not valid(score, 0) or score > 100 or not isinstance(components, (list, tuple))
            or len(components) != len(names) or any(not isinstance(row, dict) for row in components)
            or {row.get("name") for row in components} != names
            or any(not valid(row.get("score"), 0) or row["score"] > 100 for row in components)):
        return unavailable("readiness", None, "/100", "Readiness unavailable",
                           "Requires HRV, resting heart rate, sleep and load components.")
    category, label, tone = next(((key, label, tone) for boundary, key, label, tone in READINESS_BANDS
                                 if score < boundary), ("high", "High readiness", "positive"))
    return state("readiness", score, "/100", category, label, tone,
                 evidence={"components": components}, limitation=limits, provenance="Fictional weighted composite")


def load_state(recent, weekly_reference):
    context = {"reference": weekly_reference, "evidence": {"load_7": recent}}
    if not valid(recent, 0) or not valid(weekly_reference, 0) or weekly_reference == 0:
        return unavailable("load", None, "×", "Load reference unavailable",
                           "Requires a completed recent week and a nonzero prior weekly reference.", **context)
    ratio = recent / weekly_reference
    low, typical, elevated = LOAD_BANDS
    category, label, tone = (
        ("lighter", "Lighter than usual", "neutral") if ratio < low else
        ("typical", "Typical load", "neutral") if ratio <= typical else
        ("elevated", "Elevated load", "caution") if ratio <= elevated else
        ("substantial", "Substantially elevated load", "caution")
    )
    return state("load", ratio, "×", category, label, tone, **context,
                 provenance="Completed session-RPE load",
                 limitation="Reference excludes the recent seven days. Load describes training demand.")


def pace_state(selected, reference, count, basis):
    context = {"reference": reference, "evidence": {"peers": count, "basis": basis, "pace_s_per_km": selected},
               "provenance": "Whole-activity timer pace"}
    if not valid(count, MIN_PEERS) or not valid(selected, 0) or not valid(reference, 0) or not selected or not reference:
        return unavailable("pace", None, "%", "Pace comparison unavailable",
                           f"Requires a valid pace and at least {MIN_PEERS} eligible historical peers.", **context)
    percent = round(100 * (selected - reference) / reference, 10)
    near, substantial = PACE_BANDS
    category, label, tone = (
        ("much_faster", "Substantially faster", "positive") if percent <= -substantial else
        ("faster", "Faster than typical", "positive") if percent < -near else
        ("much_slower", "Substantially slower", "caution") if percent >= substantial else
        ("slower", "Slower than typical", "caution") if percent > near else
        ("near", "Near historical median", "neutral")
    )
    return state("pace", percent, "%", category, label, tone, **context,
                 limitation="Lower time per kilometre is faster. A route cohort compares whole activities.")


def percentile(value, peers, *, lower_better=False):
    clean = [p for p in peers if valid(p)]
    if len(clean) < MIN_PEERS or not valid(value):
        return None
    return 100 * sum(.5 if x == value else
                     (x > value if lower_better else x < value) for x in clean) / len(clean)


def ascent_rate(record):
    gain, distance = record.get("ascent_m"), record.get("distance_m")
    return gain * 1000 / distance if valid(gain, 0) and valid(distance, 0) and distance else None


def climb_state(selected, peers):
    rate = ascent_rate(selected)
    rates = [value for peer in peers if peer.get("sport") == selected.get("sport")
             and (value := ascent_rate(peer)) is not None]
    rank = percentile(rate, rates)
    context = {"reference": median(rates) if rates else None,
               "evidence": {"peers": len(rates), "ascent_m": selected.get("ascent_m"), "percentile": rank},
               "provenance": "Recorded FIT ascent or fictional route ascent"}
    if rank is None:
        return unavailable("climb", rate, "m/km", "Climb rank unavailable",
                           f"Requires ascent for at least {MIN_PEERS} comparable same-sport activities.", **context)
    low, typical, high = CLIMB_BANDS
    category, label, tone = (
        ("low", "Low climb demand", "neutral") if rank < low else
        ("typical", "Typical climb demand", "neutral") if rank <= typical else
        ("high", "High climb demand", "caution") if rank <= high else
        ("exceptional", "Exceptional climb demand", "caution")
    )
    return state("climb", rate, "m/km", category, label, tone, **context,
                 limitation="Percentile describes vertical gain per kilometre among comparable activities.")


def thermal_state(air, provenance=None):
    if not valid(air) or not provenance:
        return unavailable("thermal", None, "°C", "Ambient temperature unavailable",
                           "FIT device temperature can reflect body heat and exposure.")
    cool, mild, warm, elevated = THERMAL_BANDS
    category, label, tone = (
        ("cool", "Cool air", "neutral") if air < cool else
        ("mild", "Mild air", "neutral") if air < mild else
        ("warm", "Warm air", "neutral") if air < warm else
        ("elevated", "Elevated thermal context", "caution") if air < elevated else
        ("high", "High thermal context", "caution")
    )
    return state("thermal", air, "°C", category, label, tone, provenance=provenance,
                 evidence={"meteorological_heat_index": None},
                 limitation="Air temperature category only. Meteorological heat index is unavailable.")


def wind_state(bins, *, archived=False, whole_wind=None):
    widths = [row for row in bins if valid(row.get("width_m"), 0)]
    length = sum(row["width_m"] for row in widths)
    prefix = "reference_" if archived else ""
    supported = [(row["width_m"], row[prefix + "headwind_mps"], row[prefix + "crosswind_mps"])
                 for row in widths if valid(row.get(prefix + "headwind_mps")) and valid(row.get(prefix + "crosswind_mps"))]
    covered = sum(width for width, _, _ in supported)
    if not length or covered / length < .80:
        return unavailable("wind", whole_wind, "m/s", "Route wind rating unavailable",
                           "Requires valid along-track and crosswind components for 80% of the route.")
    head = sum(width * max(0, h) for width, h, _ in supported) / covered
    cross = sum(width * abs(c) for width, _, c in supported) / covered
    demand = max(head, cross)
    noticeable, strong = WIND_BANDS
    suffix = " reference" if archived else ""
    category, label, tone = (
        ("limited", f"Limited wind{suffix} demand", "neutral") if demand < noticeable else
        ("noticeable", f"Noticeable wind{suffix} demand", "caution") if demand < strong else
        ("strong", f"Strong wind{suffix} demand", "caution")
    )
    return state("wind", demand, "m/s", category, label, tone,
                 evidence={"positive_headwind_mps": head, "absolute_crosswind_mps": cross, "coverage": covered / length},
                 provenance="Fixed archived vector" if archived else "Route-resolved wind estimate or fictional fixture",
                 limitation="Absolute speed bands. Fixed archive projections describe directional exposure with constant wind.")


def trend_state(metric, recent, baseline, *, lower_better=False, unit="", relative=False):
    recent = [n for n in recent if valid(n)]
    baseline = [n for n in baseline if valid(n)]
    evidence = {"recent_count": len(recent), "baseline_count": len(baseline)}
    daily = metric in ("hrv", "resting_hr", "sleep")
    minimum_recent, minimum_baseline = MIN_DAILY_WINDOWS if daily else (MIN_PERIOD, MIN_PERIOD)
    if len(recent) < minimum_recent or len(baseline) < minimum_baseline:
        return unavailable(metric, None, unit, "Insufficient trend evidence",
                           f"Requires {minimum_recent} recent and {minimum_baseline} reference observations.", evidence=evidence)
    latest, reference = median(recent), median(baseline)
    if relative and not reference:
        return unavailable(metric, latest, unit, "Insufficient trend evidence",
                           "A relative trend requires a nonzero baseline.", evidence=evidence)
    delta = (latest - reference) / reference * 100 if relative else latest - reference
    delta = round(delta, 10)
    tolerance = TREND_TOLERANCES[metric]
    category, label, tone = ("stable", "Stable", "neutral")
    if abs(delta) > tolerance:
        if metric in ("hrv", "resting_hr", "sleep"):
            category = "higher" if delta > 0 else "lower"
            tone = "caution" if (metric == "resting_hr" and delta > 0) or (metric != "resting_hr" and delta < 0) else "neutral"
            label = "Above personal baseline" if delta > 0 else "Below personal baseline"
        else:
            improved = delta < 0 if lower_better else delta > 0
            category, label, tone = ("improving", "Improving", "positive") if improved else ("declining", "Declining", "caution")
    return state(metric, latest, unit, category, label, tone, reference=reference,
                 evidence={**evidence, "delta": delta, "tolerance": tolerance}, provenance="Fictional longitudinal history")


def workout_state(selected, peers, sport_history, climb):
    usable = [p for p in peers if valid(p.get("heart_bpm"), 0) and valid(p.get("pace_s_per_km"), 0)
              and valid(p.get("heart_coverage"), MIN_HEART_COVERAGE)]
    h = selected.get("heart_bpm")
    loss = selected.get("heart_coverage")
    pace = selected.get("pace_s_per_km")
    if len(usable) < MIN_PEERS or not all((valid(h, 0), valid(loss, MIN_HEART_COVERAGE), valid(pace, 0))):
        return unavailable("workout", None, "", "Workout unclassified",
                           "Requires adequate heart-rate time coverage and at least five peers with usable pace and heart rate.",
                           evidence={"peers": len(usable), "heart_coverage": loss})
    ref_hr, ref_pace = (median(p[key] for p in usable) for key in ("heart_bpm", "pace_s_per_km"))
    if not ref_pace:
        return unavailable("workout", None, "", "Workout unclassified", "Peer pace reference unavailable.")
    h_delta = h - ref_hr
    p_delta = (pace - ref_pace) / ref_pace * 100
    distances = [p["distance_m"] for p in sport_history if valid(p.get("distance_m"), 0)]
    long = (len(distances) >= MIN_PEERS and valid(selected.get("distance_m"), median(distances) * LONG_DISTANCE_RATIO)
            and valid(selected.get("duration_s"), LONG_DURATION_S))
    easy, high, recovery = WORKOUT_HR_BANDS
    modest = climb["category"] in ("low", "typical") and climb["value"] <= climb["reference"]
    category, label, tone = (
        ("higher_intensity", "Higher-intensity style", "caution") if p_delta < -PACE_BANDS[0] and h_delta >= high else
        ("long_endurance", "Long endurance style", "neutral") if long and h_delta < high else
        ("recovery", "Recovery-style pattern", "neutral") if p_delta >= PACE_BANDS[1] and h_delta <= -recovery and modest else
        ("easy", "Easy aerobic style", "neutral") if p_delta >= -PACE_BANDS[0] and h_delta <= -easy else
        ("steady", "Steady effort pattern", "neutral") if abs(p_delta) <= PACE_BANDS[1] and abs(h_delta) <= easy else
        ("unavailable", "Workout unclassified", "unavailable")
    )
    return state("workout", None, "", category, label, tone, reference=ref_hr,
                 evidence={"peers": len(usable), "heart_delta_bpm": h_delta, "pace_delta_pct": p_delta},
                 sufficiency="insufficient" if category == "unavailable" else "descriptive",
                 limitation="The pattern uses activity averages. Workout intent and heart-rate zones are unknown.")
