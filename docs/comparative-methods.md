# Comparative performance and environmental methods

## Running

Demo routes already use fictional Cartesian east/north metres. Length is horizontal polyline arc length.

1. Split the observed GPS polylines at missing fixes, implausible displacements, timer pauses and recording discontinuities, including intervals over 30 seconds. A fully logged pause bounded by identical fixes can stay connected as stationary elapsed time.
2. Sample each continuous Run A section on a 10 m arc-length lattice. At each station, project onto nearby Run B polyline edges and retain candidates within 15 m and 35° of travel direction. A local direction uses the chord up to 15 m either side of the station or edge midpoint.
3. Extend chains only across consecutive A stations and when B advances 5–15 m. Select the longest chain with at least 400 m of Run A distance, breaking length ties by lower summed squared separation. Each matched station preserves independent distances on A and B. This rejects isolated crossings, reverse travel and jumps between passes. Close parallel paths within tolerance or repeated laps may still be ambiguous. The reported match is a geometric estimate, and endpoints can include short portions where routes converge or diverge. Review the overlay and separation before interpreting a match.
4. Use chains of up to five steps to produce 50 m performance bins. B intervals come from the matching station distances. Pace divides each run's timer-active seconds by the **same** Run A reference distance. Aggregate pace uses endpoint-to-endpoint moving time and shared distance. Relative change is (pace B − pace A) / pace A, so negative values indicate fewer seconds per kilometre.

Here moving time means timer-active time in usable GPS intervals. Stationary time with an active timer can still contribute. Elapsed time includes a fully logged stationary pause within the aligned section. A pause accompanied by a displacement, an unknown gap, or a rejected link splits the match. No performance is interpolated across those intervals. Exact repeated distances use the first arrival at the boundary.

Heart rate uses linear partial-edge interpolation and trapezoidal time weighting over adjacent valid readings, excluding paused time. Coverage is valid contributing time divided by usable moving time.

The original pair chart withholds bin pace for bins shorter than 40 m or with B advancement outside 75–125% of A distance. Truncated endpoint bins and projecting near joins can otherwise amplify a small time or distance error into a large displayed pace change. The aggregate pace and segment bounds still use the full aligned interval.

### Historical references

History uses fictional activity distance and timer time. The primary Explorer card also shows elapsed pace or speed, which includes stops. Similar runs fall within 5.5–6.5 km for a selection in that band, otherwise within ±500 m. Same-route peers must additionally share at least 3 km and 60% of the shorter GPS route, with an aligned-length ratio of 0.85–1.15. The selected activity is excluded from both references. The middle 50% uses inclusive quartiles from four peers. From five peers, the empirical pace rank counts the proportion of peers taking more time per kilometre and adds half of ties.

The same-route profile uses complete 100 m bins on the selected route, within the best-supported continuous piece. Each historical contribution must cover the entire bin with B advancement between 75% and 125% of its A width. Pace divides each run's timer-active seconds by the same selected-route distance. It reports peer support by bin and withholds the band below four contributions. Whole-activity weather medians use available fictional peer summaries, separately from the distance-resolved pace profile.

## Cycling

- Speed is horizontal GPS distance divided by usable timer-active time. Profiles use bins up to 100 m within continuous GPS pieces. The profile axis accumulates observed distance, so displacements across gaps are omitted. Chart lines break at their boundaries.
- Grade is 100 × change in elevation divided by 100 m of horizontal route, centred on each bin. Synthetic route and terrain-model grades are separate series. Model estimates also require coverage at the 25 m checkpoints across the baseline. Sampling noise, vertical datum, grid spacing and roadside slope can affect local grade. An indicated steep bin is a review location.
- The grade chart uses a three-bin median of the route grade where all three values belong to the same continuous piece. The climb analysis uses unsmoothed grades. Grade and wind share the main Explorer map and sensor timeline cursor.
- The climb shortcut finds the steepest window of five consecutive complete 100 m route grade bins within a single continuous piece. It divides their total elevation change by 500 m and compares speed over the window using total timed distance divided by total timer-active time.
- Heading is clockwise from geographic north using atan2(east, north) on the locally smoothed chord. Weather uses meteorological direction **from** which wind arrives. For wind speed W and angle difference D = wind-from bearing − heading, headwind = W cos(D) and crosswind toward the rider's right = −W sin(D). Negative headwind is tailwind. A 10 m/s northerly wind during eastbound travel gives zero headwind and 10 m/s toward the rider's right. The diagram's arrows show travel and airflow directions.
- Wind is a projection of the source's environmental velocity. It is independent of rider speed and does not represent apparent wind, drag, gusts or shielding. Co-located speed, grade and wind are descriptive. Rider effort, stops, surface, traffic and shelter can influence speed.

All weather values in the demo are generated. They describe the fictional scenario rather than the conditions of an observed activity.
