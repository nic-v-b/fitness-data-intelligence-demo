"""Prepare an ignored, owner-local review of specifically selected FIT activities."""

import argparse
from itertools import combinations
import json
from math import atan2, cos, radians
from pathlib import Path
import subprocess
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from environmental import geographic_distance
from fit_reader import TIMESTAMP
from private_preview import PRIVATE_ROOT, normalize_run, position, projection_scale, read_selected_activity
from route_privacy import (BUNDLE_KIND, MIN_RADIUS_M, build_recorded_portfolio, edge_upper_bound,
                           retain_sections, review_path, valid_position, valid_review_radius)


COLORS = ("#66beff", "#71e2b7", "#d5a7fc", "#fab177", "#edf0a0", "#ff8e95")


def endpoints(raw):
    session, records, _ = raw
    start, elapsed = session.get(2), session.get(7)
    timed = [(record[TIMESTAMP], point) for record in records if TIMESTAMP in record
             and valid_position(point := position(record)[0])]
    if (start is None or elapsed is None or len(timed) < 2 or abs(timed[0][0] - start) > 15
            or abs(timed[-1][0] - start - elapsed / 1000) > 15):
        raise ValueError("Recorded GPS does not cover both session ends closely enough")
    return timed[0][1], timed[-1][1]


def audit_sections(entries, centres, radius):
    clearance = float("inf")
    terminals = []
    for entry in entries:
        for section in entry["sections"]:
            terminals.extend((section[0][:2], section[-1][:2]))
            for a, b in zip(section, section[1:]):
                bound = edge_upper_bound(a[:2], b[:2])
                for centre in centres:
                    da, db = (geographic_distance(row[:2], centre) for row in (a, b))
                    clearance = min(clearance, da, db, (da + db - bound) / 2)
    if not clearance > radius:
        raise ValueError("Review rejected an edge that may enter a protected area")
    # Screen for several distinct approaches ending at similar distances from the same centre.
    # This is a review cue, not a test for identifiable houses or a proof of anonymity.
    suspicious = 0
    for lat, lon in centres:
        near = []
        for a, b in terminals:
            distance = geographic_distance((lat, lon), (a, b))
            if distance <= radius + 1300:
                near.append((distance, atan2(a - lat, (b - lon) * cos(radians(lat)))))
        for triple in combinations(near, 3):
            distances = [distance for distance, _ in triple]
            if max(distances) - min(distances) <= 250 and all(
                cos(a[1] - b[1]) < .8 for a, b in combinations(triple, 2)
            ):
                suspicious += 1
                break
    return {"edge_exclusion_check": "passed", "multi_approach_patterns_for_review": suspicious,
            "property_level_inference_review": "owner review pending"}


def review_map(title, groups, *, note):
    points = [(x, y) for _, _, traces in groups for trace in traces for _, x, y in trace]
    xs, ys = zip(*points)
    width = max(1, max(xs) - min(xs))
    height = max(1, max(ys) - min(ys))
    scale = min(800 / width, 364 / height)
    mid_x, mid_y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 540">',
             '<rect width="920" height="540" rx="12" fill="#13273b"/>',
             f'<text x="32" y="43" fill="#fff" font-family="sans-serif" font-size="24">{escape(title)}</text>',
             '<text x="874" y="76" fill="#d6e4ee" font-family="sans-serif">↑ N</text>']
    for label, color, traces in groups:
        for trace in traces:
            plotted = " ".join(f"{460 + (x-mid_x)*scale:.2f},{266 - (y-mid_y)*scale:.2f}" for _, x, y in trace)
            lines.append(f'<polyline points="{plotted}" fill="none" stroke="{color}" stroke-width="2.5"/>')
    lines.append(f'<text x="32" y="477" fill="#d6e4ee" font-family="sans-serif" font-size="14">{escape(note)}</text>')
    for i, (label, color, _) in enumerate(groups):
        x, y = 32 + (i % 3) * 290, 504 + 22 * (i // 3)
        lines.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="sans-serif" font-size="15">{escape(label)}</text>')
    return "\n".join([*lines, "</svg>", ""])


def write_review(out, bundle, model, report, pair):
    out.mkdir(parents=True, exist_ok=False)
    (out / "routes.json").write_text(json.dumps(bundle, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    (out / "review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    def traces(rows):
        return [(row["name"], COLORS[i], [part.trace(None) for part in model.parts[row["id"]]])
                for i, row in enumerate(rows)]
    runs = [row for row in model.history.values() if row["sport"] == "running"]
    rides = [row for row in model.history.values() if row["sport"] == "cycling"]
    for file, title, rows in (("running-map.svg", "Recorded running · retained sections", runs),
                              ("cycling-map.svg", "Recorded cycling · retained sections", rides),
                              ("joint-map.svg", "Joint route review · retained sections only", [*runs, *rides])):
        (out / file).write_text(review_map(title, traces(rows),
            note="Owner review · gaps mark disconnected geometry · no start or finish markers"), encoding="utf-8")
    if pair:
        analysis = pair["running"]
        layers = traces([model.history[key] for key in pair["run_ids"]])
        layers.append(("Geographically matched ground", "#ffe392", [analysis["shared"]]))
        headline = f"Matched running section · {analysis['distance_m'] / 1000:.2f} km"
        readings = [f"{run['name']} {round(run['pace_s_per_km'])} s/km"
                    + (f" at {round(run['mean_heart_bpm'])} bpm" if run["mean_heart_bpm"] is not None else "")
                    for run in analysis["runs"]]
        (out / "matched-running.svg").write_text(review_map(headline, layers, note="   ·   ".join(readings)),
                                                  encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--ride", type=Path, required=True)
    parser.add_argument("--radius-m", type=float, default=MIN_RADIUS_M)
    parser.add_argument("--experimental-radius", action="store_true",
                        help="allow 500 or 750 m for an ignored owner-only comparison")
    parser.add_argument("--zones", type=Path, help="optional local JSON list of additional [latitude, longitude] centres")
    parser.add_argument("--output", type=Path, required=True, help="a new ignored directory under artifacts")
    args = parser.parse_args()
    inputs = [*args.runs, args.ride]
    if (not 2 <= len(args.runs) <= 5 or len({path.resolve() for path in inputs}) != len(inputs)
            or not valid_review_radius(args.radius_m, args.experimental_radius)):
        parser.error("Select two to five distinct staged runs and one ride. Use at least 1,000 m or opt into 500 or 750 m.")
    try:
        out = review_path(args.output)
        if out.exists() or subprocess.run(["git", "check-ignore", "-q", "--", str(out.relative_to(ROOT) / "routes.json")],
                                          cwd=ROOT).returncode:
            raise ValueError("Output must be a new ignored review directory")
        raw = [read_selected_activity(path, 1 if i < len(args.runs) else 2) for i, path in enumerate(inputs)]
        centres = [point for item in raw for point in endpoints(item)]
        if args.zones:
            local = args.zones.resolve()
            if not local.is_relative_to(PRIVATE_ROOT) or local.stat().st_size > 8192:
                raise ValueError("Extra zones belong under ignored private-data")
            extra = json.loads(local.read_text(encoding="utf-8-sig"))
            if not isinstance(extra, list) or len(extra) > 8 or not all(map(valid_position, extra)):
                raise ValueError("Use up to eight valid extra zone centres")
            centres.extend(extra)
        scale = projection_scale(raw)
        entries, original = [], []
        omitted = []
        for i, item in enumerate(raw):
            cycling = i == len(raw) - 1
            facts = []
            activity = normalize_run(item, scale, i, environmental=facts, cycling=cycling)
            sections = retain_sections(activity["samples"], facts, centres, args.radius_m,
                                       experimental=args.experimental_radius)
            if sections:
                entries.append({"sport": activity["sport"], "sections": sections})
                original.append(activity["diagnostics"]["session_distance_m"])
            else:
                omitted.append(i + 1)
        bundle = {"kind": BUNDLE_KIND, "activities": entries}
        validation = audit_sections(entries, centres, args.radius_m)
        _, _, model = build_recorded_portfolio(bundle)
        pairs = [model.compare_runs(a, b) for a, b in combinations(
            [key for key, row in model.history.items() if row["sport"] == "running"], 2)]
        best = max((pair for pair in pairs if pair and pair["running"]["available"]),
                   key=lambda pair: pair["running"]["distance_m"], default=None)
        report = {"status": "experimental owner review" if args.experimental_radius else "awaiting owner approval",
                  "radius_m": args.radius_m, "checks": validation, "omitted_input_numbers": omitted,
                  "activities": [{"name": row["name"],
                                  **({} if args.experimental_radius else
                                     {"original_km": round(distance / 1000, 2) if distance else None}),
                                  "retained_km": round(row["distance_m"] / 1000, 2),
                                  "visible_heart_coverage_pct": round((row["heart_coverage"] or 0) * 100, 1)}
                                 for distance, row in zip(original, model.history.values(), strict=True)],
                  "matching": {"eligible_pairs": sum(pair is not None for pair in pairs),
                               "longest_retained_km": round(best["running"]["distance_m"] / 1000, 2) if best else None},
                  "limitations": ["Visible distance sums retained GPS edges.",
                                  "Visible timing, ascent and heart rate omit excluded intervals and recording gaps.",
                                  "Weather, original dates and whole-activity totals are withheld from the review server.",
                                  "Safe edges do not establish anonymity. Inspect joint geography and identifiable approaches."]}
        if best is None:
            raise ValueError("No useful retained same-route pair. Choose another subset without shrinking the mask")
        write_review(out, bundle, model, report, best)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if type(error) is ValueError:
            parser.error(str(error))
        parser.error("Could not prepare the selected local recordings")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()