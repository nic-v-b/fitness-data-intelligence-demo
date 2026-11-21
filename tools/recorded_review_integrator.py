"""Combine previously protected running observations with the owner's full cycling FIT.

The bundled running routes are never reconstructed from untrimmed running FIT files.
This module only operates in the opt-in loopback review, never the public demo.
"""
from copy import deepcopy

from comparative import build_comparative
from environmental import Sources, geographic_distance
from portfolio import Portfolio
from private_preview import PRIVATE_ROOT, normalize_run, projection_scale, read_selected_activity
from route_privacy import load_recorded_review


def combine_protected_runs_and_full_ride(dataset, reviewed, full_ride, full_context, *, sources=None):
    """Replace only the bundle's clipped ride after checking its geographic identity."""
    if dataset["metadata"]["dataset_type"] != "recorded-visible-review":
        raise ValueError("Only a recorded privacy-review bundle can be combined")
    runs = [activity for activity in dataset["activities"] if activity["sport"] == "running"]
    original = [activity for activity in dataset["activities"] if activity["sport"] == "cycling"]
    if not 2 <= len(runs) <= 5 or len(original) != 1 or full_ride["sport"] != "cycling":
        raise ValueError("Expected protected running sections and one full cycling activity")
    prior_context = reviewed.contexts[original[0]["id"]]
    recorded_positions = [fact["lat_lon"] for fact in full_context if fact.get("lat_lon") is not None]
    retained_positions = [fact["lat_lon"] for fact in prior_context if fact.get("lat_lon") is not None]
    if len(recorded_positions) < 2 or len(retained_positions) < 2:
        raise ValueError("The cycling review requires geographic positions")
    # Sampling across the retained trace establishes that the candidate FIT is the
    # same ride. Comparing only endpoints would not distinguish nearby activities.
    sample_indices = {round(i * (len(retained_positions) - 1) / 8) for i in range(9)}
    if any(min(geographic_distance(retained_positions[i], candidate) for candidate in recorded_positions) > 25
           for i in sample_indices):
        raise ValueError("The full cycling FIT does not match the retained review ride")
    ride = deepcopy(full_ride)
    ride["id"], ride["name"] = original[0]["id"], original[0]["name"]
    ride.pop("visible_only", None)
    data = {**dataset,
            "metadata": {**dataset["metadata"], "cycling_full_route": True},
            "activities": [*runs, ride]}
    contexts = [reviewed.contexts[run["id"]] for run in runs] + [full_context]
    sources = sources or Sources()
    comparative = build_comparative([], ride, ride_context=full_context, sources=sources)
    portfolio = Portfolio(data, data["activities"], contexts, [None] * len(data["activities"]),
                          sources=sources, pair=comparative)
    return data, comparative, portfolio


def build_protected_local_preview(bundle, *, full_cycling=None, weather=None):
    """Load an ignored approved bundle; optionally restore one independently checked ride."""
    dataset, comparative, reviewed = load_recorded_review(bundle)
    if weather is not None and full_cycling is None:
        raise ValueError("Historical weather in this mode requires the full cycling FIT's timestamps")
    sources = Sources.load(weather, PRIVATE_ROOT) if weather is not None else Sources()
    if full_cycling is None:
        return dataset, comparative, reviewed
    raw = read_selected_activity(full_cycling, 2)
    context = []
    ride = normalize_run(raw, projection_scale([raw]), 0, environmental=context, cycling=True)
    return combine_protected_runs_and_full_ride(dataset, reviewed, ride, context, sources=sources)
