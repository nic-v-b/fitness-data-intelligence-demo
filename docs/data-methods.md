# Data and numerical methods

## Origin and coordinate system

The `ridge-traverse-v1` dataset consists of 5 km Demo Run 01 and 5 km Demo Run 02, generated from seeds `24031` and `24032`, respectively. The routes are cubic Bézier polylines in fictional Cartesian east/north metres. The generator samples each curve at 18 equal parameter intervals. Both runs reuse the same control geometry on the Ridge traverse, with distinct approaches and exits. The shared span is declared by inclusive sample indices. It is approximately 3.77 km long and contains 127 points. Fictional coordinates have no geographic datum.

Distance accumulates the Euclidean length of each horizontal polyline edge. Elapsed time accumulates edge length divided by the mean of the segment's two simulated endpoint speeds before injected faults. Source speed includes repeatable seeded variation, heart rate combines a synthetic warm-up, drift, and seeded variation, and elevation is an analytic function of position. Injected gaps and outliers affect their signal only. Time and distance remain usable. The signal models are illustrative and use no fitted parameters.

## JSON contract

The top-level `metadata` object identifies the dataset type, dataset and schema IDs, generation settings, processing version, coordinate system, units, and analysis assumptions. `activities` contains an identifier, a label, a `sport`, a `shared_segment` reference, `samples`, a `summary`, and `splits`. The timed sample fields are sport-neutral. Future observations can extend the record with units and explicit quality flags.

| Sample field | Meaning |
| --- | --- |
| `index` | Zero-based sample identity within an activity, shared by the route and timeline |
| `source` | Generator output used as input to analysis. Contains `elapsed_s`, `distance_m`, `x_m`, `y_m`, `speed_mps`, `heart_rate_bpm`, and `elevation_m` |
| `derived` | `speed_kmh` and `pace_s_per_km` calculated from the screened source speed |
| `quality` | `valid`, `missing`, or `invalid` for each optional signal |

JSON null and empty CSV fields denote absence. Quality flags distinguish missing values from invalid ones. Finite rejected readings remain in `source` and the CSV for audit, including the injected 292 bpm value. Non-finite source signals are serialized as null with an `invalid` flag. The CSV repeats its generation, units, and assumptions as JSON-encoded metadata columns so it can be interpreted by itself.

## Calculations

- **Axis validation.** The first elapsed time and cumulative distance are zero. Route coordinates and axes must be finite. Elapsed times increase strictly and cumulative distance may stay constant at a stop. A failure on an axis rejects the activity.
- **Signal quality.** The demonstration uses inclusive plausibility ranges of 0–45 m/s and 25–240 bpm. Elevation only requires a finite value. These checks screen synthetic faults and carry no clinical interpretation.
- **Speed and pace.** Speed in km/h is m/s × 3.6. Pace in s/km is 1,000 divided by positive speed in m/s. At zero speed, speed remains zero and pace is undefined. Average speed uses total distance divided by total elapsed time, including stops. Average pace is based on that average speed.
- **Interpolation.** For target `x` between adjacent values `x₀` and `x₁`, use fraction `(x − x₀) / (x₁ − x₀)` on the other fields. Interpolate a signal only if both endpoints are valid. An exact target returns its screened sample. Distance plateaus use the first arrival at an exact boundary. Outside the activity, interpolation returns null.
- **Distance splits.** Compute 1 km boundary times via distance interpolation and difference successive times. A shorter final split uses the final recorded time. If a stop occurs at the exact final full boundary, time after first arrival contributes only to the activity summary. A stop at an intermediate boundary contributes to the following split.
- **Heart-rate mean.** Trapezoidal time-weighting uses only intervals bounded by two valid readings. Coverage is the contributing duration divided by the full elapsed duration. Long gaps can lower coverage and change the interpretation of the mean.
- **Elevation gain.** Sum positive changes on adjacent valid pairs. This estimate excludes any change across gaps and depends on sampling density. The application applies no noise filter.
- **Browser display.** Each chart uses elapsed time on its horizontal axis. Pointer selection snaps to the nearest time sample and the route marker uses that sample's source coordinates. The keyboard slider steps by sample index. Route segment colours use the mean of the two endpoint readings, with a fixed scale per metric across activities. Segments with an unusable endpoint are grey. Charts break at gaps and show a hollow marker at the baseline when the selected reading is unavailable. Rounding, colouring, and screen projections apply to display only.

## Hand-checkable references

| Input | Expected result |
| --- | --- |
| 4 m/s | 14.4 km/h and 250 s/km (4:10/km) |
| 0 m at 0 s and 400 m at 100 s | 200 m at 50 s in either direction |
| 1,000 m at 250 s and again at 280 s | First 1 km split ends at 250 s |
| 1,500 m at 380 s and 2,300 m at 580 s | 2,000 m at 505 s, with 75 s over the final 300 m |
| 100 and 120 bpm at 0 and 10 s, missing at 20 s, 160 and 180 bpm at 50 and 60 s | 140 bpm over 20 valid seconds, or one-third coverage |
| 100 m, 103 m, missing, 110 m, and 108 m elevation | 3 m gain from adjacent valid pairs |

The automated suite covers these references. The synthetic fixture supports individual activity inspection and uses a declared shared section.

## Private FIT preview

The optional reader covers a single running session per Garmin Activity FIT file. It validates the file signature, declared length, and checksum, and reads the standard file, session, record, and timer-event fields this view needs. It handles ordinary and compressed timestamps, per-definition byte order, and FIT null sentinels. Other messages and developer fields are skipped. The synthetic default and regression fixtures require no device files. [Garmin FIT protocol](https://developer.garmin.com/fit/protocol/)

- **Geography.** Activity Explorer draws recorded GPS positions on a shared north-up equirectangular projection at the local reference latitude. GPS coordinates and route images remain identifiable even when filenames and activity titles are omitted. The separate comparison view uses geometry-based alignment. [Comparison methods](comparative-methods.md)
- **Recorded samples.** Distance, heart rate, speed, and elevation come from FIT records. Speed and elevation use enhanced FIT fields when present, with standard-field fallback. Pace at a sample is calculated from recorded speed. An absent field stays unavailable. Distance decreases are flagged and excluded from distance calculations.
- **Elapsed time and gaps.** The time axis starts at the recorded session start when available and consistent, with the first usable timestamp as fallback. Observations without usable or increasing timestamps are excluded and counted. Both timelines and route traces break on intervals overlapping timer pauses, gaps over 30 seconds, or skipped timestamp records. The route also breaks on missing GPS or a displacement above both 20 m and 15 m/s on an otherwise continuous interval. GPS checks flag edges and keep the recorded points.
- **Summaries and splits.** Headline elapsed time and distance come from the last sample. Elapsed pace includes pauses. The validation panel lists the recorded FIT timer time separately. A speed-based moving time is outside the preview's scope. Split boundaries use recorded cumulative distance and withhold a time when a boundary requires interpolation across a gap or unavailable distance. The heart-rate mean uses time-weighted adjacent pairs outside gaps and paused intervals. The ascent card uses the FIT session total. The validation panel separately reports the unfiltered sum of positive changes between valid elevation samples, which is sensitive to noise and can exceed the device total.
- **Local access.** The preview reads only explicitly selected files under `private-data/`. It keeps the browser dataset in memory, drops absolute timestamps and source filenames, and serves an allowlisted dataset response with `Cache-Control: no-store` on loopback. Private exports and raw-file access are disabled. The displayed route remains sensitive. This mode is for owner-local review.

The reader is intentionally scoped to these FIT fields. Validation of additional devices, file variants, and sports is outside the preview.
