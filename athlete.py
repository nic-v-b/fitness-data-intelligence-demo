"""Deterministic athlete history, descriptive metrics and an illustrative week."""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from health import SCENARIOS, SESSION_EFFORT, summarize_health, training_load
from insights import plan_takeaway, profile_takeaway
from semantics import LOAD_BANDS, PLAN_READINESS_GUARD, load_state, readiness_state, trend_state

START = date(2026, 1, 5)
WEEKS = 36
SPORTS = ("running", "cycling")


def fictional_history(scenario="typical"):
    activities = []
    benchmarks = {7: 1572, 15: 1514, 23: 1526, 31: 1461, 35: 1448}
    for week in range(WEEKS):
        monday = START + timedelta(weeks=week)
        phase = week / (WEEKS - 1)
        cutback = .76 if week % 4 == 3 and week not in benchmarks else 1
        sessions = []
        if week not in (10, 21):
            easy_m = round((4000 + 1700 * phase + 200 * (week % 3)) * cutback / 100) * 100
            long_m = round((6900 + 4800 * phase + 400 * (week % 3)) * cutback / 100) * 100
            sessions.extend((
                (1, "running", "Easy run", easy_m, round(easy_m / 1000 * (391 - 23 * phase + 4 * (week % 3)))),
                (5, "running", "Long easy run", long_m, round(long_m / 1000 * (403 - 20 * phase))),
            ))
            if week % 5 != 2 or week in benchmarks:
                mid_m = round((4300 + 2400 * phase) * cutback / 100) * 100
                sessions.append((3, "running", "5 km benchmark", 5000, benchmarks[week]) if week in benchmarks else
                                (3, "running", "Steady run", mid_m, round(mid_m / 1000 * (363 - 20 * phase))))
        if week != 21:
            ride_m = round((18700 + 18000 * phase + 2400 * (week % 4)) * cutback / 100) * 100
            sessions.append((6, "cycling", "Aerobic ride", ride_m, round(ride_m * 3.6 / (22 + 2.1 * phase))))
            if week > 13 and week % 3 == 1:
                sessions.append((2, "cycling", "Easy spin", 13200, 2160))
        if scenario == "compressed" and week == WEEKS - 1:
            sessions.extend(((2, "cycling", "Aerobic ride", 25400, 3840),
                             (4, "running", "Easy run", 4200, 1600)))
        for offset, sport, name, distance, duration in sorted(sessions):
            activities.append({"id": f"fiction-{len(activities) + 1}", "date": (monday + timedelta(days=offset)).isoformat(),
                               "sport": sport, "session": name, "distance_m": distance, "duration_s": duration,
                               "rpe": SESSION_EFFORT[name]})
    return activities


def totals(activities):
    return {sport: {
        "count": sum(row["sport"] == sport for row in activities),
        "distance_m": sum(row["distance_m"] for row in activities if row["sport"] == sport),
        "duration_s": sum(row["duration_s"] for row in activities if row["sport"] == sport),
    } for sport in SPORTS}


def period_summary(key, activities):
    return {"period": key, "totals": totals(activities), "days": len({row["date"] for row in activities})}


def summarize_history(activities):
    weeks, months = defaultdict(list), defaultdict(list)
    for row in activities:
        day = date.fromisoformat(row["date"])
        weeks[(day - timedelta(days=day.weekday())).isoformat()].append(row)
        months[row["date"][:7]].append(row)
    weekly = [period_summary((START + timedelta(weeks=i)).isoformat(), weeks[(START + timedelta(weeks=i)).isoformat()])
              for i in range(WEEKS)]
    monthly = [period_summary(month, rows) for month, rows in sorted(months.items())]
    recent_day = (START + timedelta(weeks=WEEKS - 4)).isoformat()
    recent = [row for row in activities if row["date"] >= recent_day]
    running = [row for row in activities if row["sport"] == "running"]
    cycling = [row for row in activities if row["sport"] == "cycling"]
    benchmarks = [row for row in running if row["session"] == "5 km benchmark"]
    return {"lifetime": totals(activities), "recent": totals(recent), "weekly": weekly, "monthly": monthly,
            "recent_active_weeks": sum(row["days"] > 0 for row in weekly[-8:]),
            "recent_training_days": len({row["date"] for row in recent}),
            "benchmarks": benchmarks,
            "records": {"fastest_5k": min(benchmarks, key=lambda row: row["duration_s"]),
                        "longest_run": max(running, key=lambda row: row["distance_m"]),
                        "longest_ride": max(cycling, key=lambda row: row["distance_m"])}}


def suggested_week(activities, profile, health):
    last_four = profile["weekly"][-4:]
    recent = [row for row in activities if row["date"] >= last_four[0]["period"]]
    recent_runs = [row for row in recent if row["sport"] == "running"]
    recent_rides = [row for row in recent if row["sport"] == "cycling"]
    baseline = {
        "median_run_m": median(week["totals"]["running"]["distance_m"] for week in last_four),
        "last_run_m": last_four[-1]["totals"]["running"]["distance_m"],
        "median_run_sessions": median(week["totals"]["running"]["count"] for week in last_four),
        "longest_recent_run_m": max(row["distance_m"] for row in recent_runs),
        "recent_paced_sessions": sum(row["session"] in ("Steady run", "5 km benchmark") for row in recent_runs),
        "median_ride_m": median(row["distance_m"] for row in recent_rides),
    }
    recent_load = health["latest"]["load_7"]
    typical_load = health["latest"]["load_reference"]
    readiness_score = health["latest"]["readiness"]
    guarded = readiness_score < PLAN_READINESS_GUARD or recent_load > LOAD_BANDS[1] * typical_load
    run_time = median(row["duration_s"] / row["distance_m"] for row in recent_runs)
    ride_time = median(row["duration_s"] / row["distance_m"] for row in recent_rides)
    baseline.update(readiness=readiness_score, load_7=round(recent_load), typical_load=round(typical_load),
                    volume_guard=guarded, semantic=health["semantic"])
    # Round down to half-kilometres and cap the proposal at both observed volume references.
    cap = min(baseline["median_run_m"], baseline["last_run_m"]) * (.8 if guarded else 1)
    choices = []
    for label, fraction in (("Standard", 1), ("Lighter", .75)):
        budget = int(cap * fraction // 500) * 500
        easy = budget // 2000 * 500
        steady = round(budget * .30 / 500) * 500
        long = min(budget - easy - steady, baseline["longest_recent_run_m"] // 500 * 500)
        ride = int(baseline["median_ride_m"] * fraction * (.8 if guarded else 1) // 1000) * 1000
        steady_allowed = fraction == 1 and not guarded and baseline["recent_paced_sessions"] >= 2
        sessions = [
            ("Rest", "Keep the day open.", None, 0),
            ("Easy run", "Keep the effort conversational.", "running", easy),
            ("Rest", "Keep the day open before the next run.", None, 0),
            ("Controlled steady run" if steady_allowed else "Easy run",
             "Run the middle portion at a sustainable effort." if steady_allowed
             else "Keep the full session conversational.", "running", steady),
            ("Rest", "Keep the day open before the longer run.", None, 0),
            ("Long easy run", "Use a comfortable, familiar effort.", "running", long),
            ("Easy cycling", "Keep the effort light after the longer run.", "cycling", ride),
        ]
        days = [{"date": (START + timedelta(weeks=WEEKS, days=i)).isoformat(), "session": name,
                 "detail": detail, "sport": sport, "distance_m": distance,
                 "duration_s": round(distance * (ride_time if sport == "cycling" else run_time)),
                 "rpe": SESSION_EFFORT.get(name, 0)}
                for i, (name, detail, sport, distance) in enumerate(sessions)]
        choices.append({"label": label, "days": days, "load": round(sum(
            training_load(day["duration_s"], day["rpe"]) for day in days
        )), "paced": steady_allowed, "totals": {
            sport: sum(day["distance_m"] for day in days if day["sport"] == sport) for sport in SPORTS
        }})
        choices[-1]["takeaway"] = plan_takeaway(baseline, choices[-1], choices[0])
    return {"baseline": baseline, "alternatives": choices, "objective": "Build repeatable 5 km endurance"}


def athlete_demo(scenario="typical"):
    if scenario not in SCENARIOS:
        raise ValueError("Use a defined fictional training scenario")
    activities = fictional_history(scenario)
    profile = summarize_history(activities)
    morning = START + timedelta(weeks=WEEKS)
    health = summarize_health(activities, profile["benchmarks"], START, morning, scenario)
    days = health["daily"]
    recent, baseline = days[-7:], days[-35:-7]
    benchmark = [item["benchmark_s"] for item in health["vo2max"]]
    aerobic = [item["estimate"] for item in health["vo2max"]]
    weeks = profile["weekly"]
    active = [sum(bool(week["days"]) for week in weeks[i:i + 4]) for i in range(len(weeks) - 16, len(weeks), 4)]
    health["semantic"] = {
        "readiness": readiness_state(health["latest"]["readiness"], health["latest"]["components"]),
        "load": load_state(health["latest"]["load_7"], health["latest"]["load_reference"]),
        "benchmark": trend_state("benchmark", benchmark[-2:], benchmark[-4:-2], lower_better=True, unit="s / 5 km", relative=True),
        "vo2max": trend_state("vo2max", aerobic[-2:], aerobic[-4:-2], unit="mL/kg/min"),
        "consistency": trend_state("consistency", active[-2:], active[:2], unit="active weeks per four"),
        **{metric: trend_state(metric, [row[key] for row in recent], [row[key] for row in baseline], unit=unit)
           for metric, key, unit in (("hrv", "hrv_ms", "ms"), ("resting_hr", "resting_bpm", "bpm"),
                                     ("sleep", "sleep_min", "min"))},
    }
    return {"source": "Deterministic fictional athlete history", "name": "Avery Chen",
            "through": (morning - timedelta(days=1)).isoformat(),
            "scenario": scenario, "scenarios": SCENARIOS,
            "activities": activities, "profile": profile, "health": health, "takeaway": profile_takeaway(health, profile),
            "planner": suggested_week(activities, profile, health)}
