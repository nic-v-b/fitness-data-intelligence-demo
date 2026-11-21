"""Deterministic, evidence-grounded conclusions for the three analytical views."""

from semantics import LOAD_BANDS, MIN_PEERS, PACE_BANDS, PLAN_READINESS_GUARD, WORKOUT_HR_BANDS


def pace_text(seconds):
    rounded = round(seconds)
    return f"{rounded // 60}:{rounded % 60:02d}/km"


def sleep_text(minutes):
    return f"{minutes // 60} h {minutes % 60:02d} min"


def environment_evidence(detail):
    weather = detail["activity_weather"] or detail.get("fictional_conditions")
    if not weather:
        return None
    origin = "Whole-activity archive estimate" if detail["activity_weather"] else "Fictional weather"
    pieces = [
        f"{weather['air_temperature_c']:.1f}°C air" if weather["air_temperature_c"] is not None else None,
        f"{weather['wind_speed_mps']:.1f} m/s wind" if weather["wind_speed_mps"] is not None else None,
    ]
    return (origin, " · ".join(part for part in pieces if part)) if any(pieces) else None


def explorer_takeaway(detail, pair_index=None):
    selected, labels = detail["history"], detail["semantic"]
    visible = detail.get("activity", {}).get("visible_only")
    climb, thermal, wind, workout = (labels[key] for key in ("climb", "thermal", "wind", "workout"))
    facts = []
    sentences = []
    tags = [workout, climb]
    if selected["sport"] == "cycling":
        ride = detail["cycling"]
        ascent = ride.get("strongest_climb")
        if ascent:
            sentences.append(f"The strongest 500 m ascent averaged {ascent['grade_pct']:.1f}% near "
                             f"kilometre {ascent['distance_m'] / 1000:.1f}.")
            facts.append(("Climb", f"{ascent['distance_m'] / 1000:.2f} km midpoint · "
                          f"{ascent['speed_kmh']:.1f} km/h · unsmoothed grade"))
        if wind["provenance"] == "Fixed archived vector":
            sentences.append("The fixed archive wind reference shows how changes in heading alter estimated exposure.")
        elif wind["sufficiency"] == "supported":
            sentences.append(f"The route profile indicates {wind['label'].lower()}, using along-track and crosswind components.")
        if climb["sufficiency"] == "insufficient":
            sentences.append("Comparable rides are too few to rank this effort.")
        tags.extend((wind, thermal))
        if wind["sufficiency"] == "supported":
            evidence = wind["evidence"]
            facts.append(("Modeled wind exposure", f"{evidence['positive_headwind_mps']:.1f} m/s mean positive headwind · "
                          f"{evidence['absolute_crosswind_mps']:.1f} m/s mean absolute crosswind · {wind['provenance']}"))
    else:
        ref = labels["route_pace"]
        if ref["sufficiency"] != "supported":
            ref = labels["similar_pace"]
        tags.append(ref)
        if ref["sufficiency"] == "supported":
            delta, basis = ref["value"], ref["evidence"]["basis"]
            workout_phrase = {
                "steady": "The pace and heart rate are consistent with a steady effort.",
                "easy": "The pace and lower heart rate are consistent with an easy aerobic effort.",
                "recovery": "The pace, heart rate and ascent are consistent with a recovery-style effort.",
                "higher_intensity": "The faster pace and higher heart rate suggest a higher-intensity effort.",
                "long_endurance": "The distance, duration and relative heart rate fit a long endurance effort.",
            }.get(workout["category"])
            if workout_phrase:
                sentences.append(workout_phrase)
            pace = "near" if ref["category"] == "near" else f"{abs(delta):.1f}% {'faster' if delta < 0 else 'slower'} than"
            heart_delta = workout["evidence"].get("heart_delta_bpm")
            same_basis = basis == "same-route"
            if (same_basis and workout["evidence"].get("peers", 0) >= MIN_PEERS and delta < -PACE_BANDS[0]
                    and heart_delta is not None and abs(heart_delta) <= WORKOUT_HR_BANDS[0]):
                sentences.append(f"Pace was {pace} the same-route median at a similar average heart rate. "
                                 "That suggests stronger performance at a comparable recorded effort for this run.")
                facts.append(("Interpretation limit", "One workout cannot establish a fitness trend. Heart rate is an effort proxy."))
            else:
                sentences.append(f"Timer pace was {pace} the {basis} median.")
                if not workout_phrase and heart_delta is not None and abs(heart_delta) <= WORKOUT_HR_BANDS[0]:
                    sentences.append("Average heart rate was close to its peer reference, so pace alone gives weak evidence about effort.")
            facts.append(("Pace comparison", f"{pace_text(selected['pace_s_per_km'])} vs {pace_text(ref['reference'])} "
                          f"across {ref['evidence']['peers']} peers · {basis} whole activities"))
            if heart_delta is not None:
                facts.append(("Mean heart rate vs comparable runs", f"{selected['heart_bpm']:.0f} vs "
                              f"{workout['reference']:.0f} bpm · {workout['evidence']['peers']} usable references"))
        elif pair_index is not None:
            pair = detail["pair"]["running"]
            run, other = pair["runs"][pair_index], pair["runs"][1 - pair_index]
            sentences.append(f"The {pair['distance_m'] / 1000:.2f} km shared section supports a direct comparison of these "
                             "two runs. The historical sample is still too small to classify the effort or establish a trend.")
            if run["pace_s_per_km"] and other["pace_s_per_km"]:
                facts.append(("Shared-section pace", f"{pace_text(run['pace_s_per_km'])} vs {pace_text(other['pace_s_per_km'])}"))
            if run["mean_heart_bpm"] is not None and other["mean_heart_bpm"] is not None:
                facts.append(("Shared-section heart rate", f"{run['mean_heart_bpm']:.0f} vs {other['mean_heart_bpm']:.0f} bpm"))
        elif visible and detail["peer_context"]["peer_ids"]:
            peers = len(detail["peer_context"]["peer_ids"])
            sentences.append(f"Compare pace and heart rate against {peers} same-route "
                             f"{'recording' if peers == 1 else 'recordings'} on the retained shared ground.")
        else:
            sentences.append(f"Fewer than {MIN_PEERS} eligible peers are available to classify the run’s pace.")
        if thermal["category"] in ("elevated", "high"):
            sentences.append("The air temperature adds thermal context. Its effect on pace is uncertain.")
        tags.append(thermal)
    if selected["heart_bpm"] is not None:
        facts.append(("Visible mean heart rate" if visible else "Activity mean heart rate", f"{selected['heart_bpm']:.0f} bpm"))
    if climb["value"] is not None:
        rank = climb["evidence"]["percentile"]
        detail_text = f" · {rank:.0f}th percentile across {climb['evidence']['peers']} peers" if rank is not None else ""
        facts.append(("Ascent", f"{selected['ascent_m']:.0f} m · {climb['value']:.1f} m/km{detail_text}"))
    weather = environment_evidence(detail)
    if weather:
        facts.append(weather)
        if thermal["sufficiency"] == "supported":
            facts.append(("Thermal method", thermal["limitation"]))
    if not sentences:
        sentences.append("The ride has insufficient terrain and historical evidence for an effort classification.")
    return {"text": " ".join(sentences), "facts": facts, "states": tags}


def profile_takeaway(health, profile):
    labels = health["semantic"]
    b, v, h, r, s, load, score = (labels[key] for key in
                                  ("benchmark", "vo2max", "hrv", "resting_hr", "sleep", "load", "readiness"))
    supporting = []
    if b["category"] == v["category"] == "improving":
        supporting.append("Recent 5 km benchmarks and the performance-based VO₂max estimate both improved.")
    else:
        supporting.append(f"The benchmark trend is {b['label'].lower()} and the VO₂max estimate is {v['label'].lower()}.")
    if load["tone"] == "caution" and s["category"] == "lower" and h["category"] == "lower":
        supporting.append("Recent demand is above baseline while sleep and HRV are lower. "
                          "That combination supports a more conservative week in this scenario.")
    elif h["category"] == r["category"] == "stable":
        supporting.append("HRV and resting heart rate remain near their personal baselines.")
    supporting.append(f"Training was recorded in {profile['recent_active_weeks']} of the last eight weeks.")
    recent = health["recent"]
    facts = []
    if b["sufficiency"] == "supported":
        facts.append(("5 km benchmark medians", f"{b['value']:.0f} vs {b['reference']:.0f} s · two tests per window"))
    if v["sufficiency"] == "supported":
        facts.append(("VO₂max estimate medians", f"{v['value']:.1f} vs {v['reference']:.1f} mL/kg/min"))
    for title, condition in (("HRV", h), ("Resting heart rate", r), ("Sleep", s)):
        if condition["sufficiency"] == "supported":
            format_value = (lambda n: sleep_text(round(n))) if condition["unit"] == "min" else (
                lambda n: f"{n:.1f} {condition['unit']}"
            )
            facts.append((title, f"{format_value(condition['value'])} recent median vs "
                          f"{format_value(condition['reference'])} prior median"))
    if load["sufficiency"] == "supported":
        facts.append(("Completed load", f"{recent['load_7']:,} units in 7 days · {recent['prior_weekly_load']:,} per prior reference week"))
    if score["sufficiency"] == "supported":
        facts.append(("Readiness", f"{score['value']}/100 · illustrative composite"))
    return {
        "text": " ".join(supporting), "states": [b, load, score], "facts": facts,
    }


def plan_takeaway(baseline, choice, standard):
    labels = baseline["semantic"]
    load, score = labels["load"], labels["readiness"]
    if baseline["volume_guard"]:
        explanation = ("The volume guard reduces the starting distance budgets and keeps the runs easy. "
                       "Recent training demand and the illustrative morning score favour holding back.")
        if choice["label"] == "Lighter":
            explanation += " The lighter option reduces the distance further at the same easy intensity."
    elif choice["paced"]:
        explanation = ("Load is within its usual range and readiness supports maintaining volume "
                       "with one controlled steady run.")
    else:
        explanation = "The lighter option trims volume and keeps the runs easy while the morning readiness score stays the same."
    reduction = (f" · {standard['load'] - choice['load']:,} fewer units than Standard"
                 if choice["label"] == "Lighter" else "")
    return {
        "text": (f"{explanation} With readiness at {score['value']}/100, the {choice['label'].lower()} week proposes "
                 f"{choice['totals']['running'] / 1000:g} km of running and about {choice['load']:,} load units."),
        "states": [load, score],
        "facts": [
            ("Completed training", f"{baseline['load_7']:,} units in 7 days · {baseline['typical_load']:,} per prior reference week · "
             f"{load['value']:.2f}×"),
            ("Readiness and sleep", f"{score['value']}/100 · {labels['sleep']['label'].lower()}"),
            ("Volume guard", f"Readiness below {PLAN_READINESS_GUARD} or recent load above "
             f"{LOAD_BANDS[1]:.0%} of the nonoverlapping reference."),
            ("Planned distance", f"{choice['totals']['running'] / 1000:g} km running · "
             f"{choice['totals']['cycling'] / 1000:g} km cycling"),
            ("Projected load", f"{choice['load']:,} units from planned duration and session effort{reduction}"),
        ],
    }
