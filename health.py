"""Fictional daily observations and transparent training-context calculations."""

from collections import defaultdict
from datetime import timedelta
from math import cos, sin
from statistics import fmean, median


SCENARIOS = {"typical": "Typical week", "compressed": "Heavier, shorter-sleep week"}
SESSION_EFFORT = {"Easy run": 3, "Long easy run": 4, "Steady run": 5, "Controlled steady run": 5,
                  "5 km benchmark": 8, "Aerobic ride": 4, "Easy spin": 2, "Easy cycling": 3}


def training_load(duration_s, effort):
    """Session-RPE load in arbitrary units."""
    return duration_s * effort / 60


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def readiness(observations, hrv_baseline_ms, resting_baseline_bpm, load_7, load_28_weekly):
    """Return an illustrative composite and its weighted inputs."""
    hrv = clamp(83 + 150 * (observations["hrv_ms"] / hrv_baseline_ms - 1))
    resting = clamp(90 - 5 * (observations["resting_bpm"] - resting_baseline_bpm))
    sleep = clamp(100 * observations["sleep_min"] / 480)
    increase = max(0, (load_7 - load_28_weekly) / load_28_weekly) if load_28_weekly else 0
    load = clamp(91 - 95 * increase)
    parts = [{"name": name, "score": round(score, 1), "weight": weight}
             for name, score, weight in (("HRV", hrv, .30), ("Resting heart rate", resting, .15),
                                         ("Sleep duration", sleep, .30), ("Training load", load, .25))]
    return round(sum(part["score"] * part["weight"] for part in parts)), parts


def daily_health(activities, start, morning, scenario):
    daily_load = defaultdict(float)
    for activity in activities:
        daily_load[activity["date"]] += training_load(activity["duration_s"], activity["rpe"])
    days = []
    for index in range((morning - start).days + 1):
        date = start + timedelta(days=index)
        day = date.isoformat()
        yesterday = daily_load[(date - timedelta(days=1)).isoformat()]
        short_sleep = scenario == "compressed" and (morning - date).days < 6
        sleep = round(clamp(462 + 24 * sin(.72 * index - 1.1) + 13 * cos(.31 * index)
                            - (83 if short_sleep else 0), 315, 540))
        lost_sleep = max(0, 450 - sleep)
        adaptation = index / (morning - start).days
        observed = {
            "hrv_ms": round(clamp(54 + 7 * adaptation + 3.7 * sin(.65 * index)
                                  - yesterday * .016 - lost_sleep * .11, 28, 84), 1),
            "resting_bpm": round(clamp(59 - 4 * adaptation + 1.45 * cos(index * .61)
                                       + yesterday * .007 + lost_sleep * .045, 43, 76), 1),
            "sleep_min": sleep,
            "sleep_quality": int(clamp(round(3.7 + (sleep - 450) / 78 + .6 * sin(index * 1.17)), 1, 5)),
        }
        load_7 = sum(point["session_load"] for point in days[-7:]) if index >= 7 else None
        load_28 = sum(point["session_load"] for point in days[-28:]) if index >= 28 else None
        load_reference = sum(point["session_load"] for point in days[-35:-7]) / 4 if index >= 35 else None
        score, parts = None, []
        if load_28 is not None:
            baseline = days[-28:]
            score, parts = readiness(observed, median(p["hrv_ms"] for p in baseline),
                                     median(p["resting_bpm"] for p in baseline), load_7, load_28 / 4)
        days.append({"date": day, **observed, "session_load": daily_load[day],
                     "load_7": load_7, "load_28": load_28, "load_reference": load_reference,
                     "readiness": score, "components": parts})
    return days


def aerobic_estimate(benchmark):
    # Running oxygen cost in a flat standardized effort and one assumed fraction of maximum.
    speed = benchmark["distance_m"] * 60 / benchmark["duration_s"]
    return round((3.5 + .2 * speed) / .90, 1)


def summarize_health(activities, benchmarks, start, morning, scenario):
    days = daily_health(activities, start, morning, scenario)
    recent, baseline = days[-7:], days[-35:-7]
    latest = days[-1]
    return {
        "daily": days, "latest": latest,
        "recent": {
            "hrv_ms": round(median(point["hrv_ms"] for point in recent), 1),
            "resting_bpm": round(median(point["resting_bpm"] for point in recent), 1),
            "sleep_min": round(fmean(point["sleep_min"] for point in recent)),
            "sleep_quality": round(fmean(point["sleep_quality"] for point in recent), 1),
            "baseline_hrv_ms": round(median(point["hrv_ms"] for point in baseline), 1),
            "baseline_resting_bpm": round(median(point["resting_bpm"] for point in baseline), 1),
            "load_7": round(latest["load_7"]),
            "load_28": round(latest["load_28"]),
            "weekly_equivalent_load": round(latest["load_28"] / 4),
            "prior_weekly_load": round(latest["load_reference"]),
        },
        "vo2max": [{"date": sample["date"], "estimate": aerobic_estimate(sample),
                    "benchmark_s": sample["duration_s"]} for sample in benchmarks],
    }
