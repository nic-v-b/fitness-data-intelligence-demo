# Comparative performance and environmental methods

## Running

FIT GPS positions use Garmin semicircles multiplied by 180 / 2³¹ to obtain WGS84 degrees. Local equirectangular east/north metres use a spherical radius of 6,371,008.8 m and the midpoint latitude of the selected routes. Length is horizontal polyline arc length. Distances can differ slightly from the device odometer. This projection is intended for local activities. Antimeridian-spanning selections are rejected. Projected route coordinates still identify locations.

1. Split the observed GPS polylines at missing fixes, implausible displacements, timer pauses and recording discontinuities, including intervals over 30 seconds. A fully logged pause bounded by identical fixes can stay connected as stationary elapsed time.
2. Sample each continuous Run A section on a 10 m arc-length lattice. At each station, project onto nearby Run B polyline edges and retain candidates within 15 m and 35° of travel direction. A local direction uses the chord up to 15 m either side of the station or edge midpoint.
3. Extend chains only across consecutive A stations and when B advances 5–15 m. Select the longest chain with at least 400 m of Run A distance, breaking length ties by lower summed squared separation. Each matched station preserves independent distances on A and B. This rejects isolated crossings, reverse travel and jumps between passes. Close parallel paths within tolerance or repeated laps may still be ambiguous. The reported match is a geometric estimate, and endpoints can include short portions where routes converge or diverge. Review the overlay and separation before interpreting a match.
4. Use chains of up to five steps to produce 50 m performance bins. B intervals come from the matching station distances. Pace divides each run's timer-active seconds by the **same** Run A reference distance. Aggregate pace uses endpoint-to-endpoint moving time and shared distance. Relative change is (pace B − pace A) / pace A, so negative values indicate fewer seconds per kilometre.

Here moving time means timer-active time in usable GPS intervals. Stationary time with an active timer can still contribute. Elapsed time includes a fully logged stationary pause within the aligned section. A pause accompanied by a displacement, an unknown gap, or a rejected link splits the match. No performance is interpolated across those intervals. Exact repeated distances use the first arrival at the boundary.

Heart rate and device temperature use linear partial-edge interpolation and trapezoidal time weighting over adjacent valid readings, excluding paused time. Coverage is valid contributing time divided by usable moving time. FIT record field 13 uses signed whole degrees Celsius. Its measurement environment and sensor placement are device-dependent. Exposure, clothing and body heat can affect readings.

The original pair chart withholds bin pace for bins shorter than 40 m or with B advancement outside 75–125% of A distance. Truncated endpoint bins and projecting near joins can otherwise amplify a small time or distance error into a large displayed pace change. The aggregate pace and segment bounds still use the full aligned interval.

### Historical references

History uses session distance and timer time where the device has supplied them. The primary Explorer card also shows elapsed pace or speed, which includes stops. Similar runs fall within 5.5–6.5 km for a selection in that band, otherwise within ±500 m. Same-route peers must additionally share at least 3 km and 60% of the shorter GPS route, with an aligned-length ratio of 0.85–1.15. Candidate FITs need at least 90% valid positions. The selected recording is excluded from both references. The middle 50% uses inclusive quartiles from four peers. From five peers, the empirical pace rank counts the proportion of peers taking more time per kilometre and adds half of ties.

The same-route profile uses complete 100 m bins on the selected route, within the best-supported continuous piece. Each historical contribution must cover the entire bin with B advancement between 75% and 125% of its A width. Pace divides each run's timer-active seconds by the same selected-route distance. It reports peer support by bin and withholds the band below four contributions. Whole-activity weather medians use available peer summaries from the same source, separately from the distance-resolved pace profile.

## Cycling

- Speed is horizontal GPS distance divided by usable timer-active time. Profiles use bins up to 100 m within continuous GPS pieces. The profile axis accumulates observed distance, so displacements across gaps are omitted. Chart lines break at their boundaries.
- Grade is 100 × change in elevation divided by 100 m of horizontal route, centred on each bin. FIT recorded and terrain-model grades are separate series. Model estimates also require coverage at the 25 m checkpoints across the baseline. Sampling noise, vertical datum, grid spacing and roadside slope can affect local grade. An indicated steep bin is a review location.
- The grade chart uses a three-bin median of the FIT grade where all three values belong to the same continuous piece. The climb analysis uses unsmoothed grades. Grade and wind share the main Explorer map and sensor timeline cursor.
- The climb shortcut finds the steepest window of five consecutive complete 100 m FIT grade bins within a single continuous piece. It divides their total elevation change by 500 m and compares speed over the window using total timed distance divided by total timer-active time.
- Heading is clockwise from geographic north using atan2(east, north) on the locally smoothed chord. Weather uses meteorological direction **from** which wind arrives. For wind speed W and angle difference D = wind-from bearing − heading, headwind = W cos(D) and crosswind toward the rider's right = −W sin(D). Negative headwind is tailwind. A 10 m/s northerly wind during eastbound travel gives zero headwind and 10 m/s toward the rider's right. The diagram's arrows show travel and airflow directions.
- Wind is a projection of the source's environmental velocity. It is independent of rider speed and does not represent apparent wind, drag, gusts or shielding. Co-located speed, grade and wind are descriptive. Rider effort, stops, surface, traffic and shelter can influence speed.

## Owner-local observations

The local adapter accepts one weather product and one terrain product via `--environment`. It sends no requests. Archive index annotations, source recommendations, climate normals and unverified labels do not supply observations. Load numeric values only when their source and units are documented, and retain the original extract locally for audit.

Place JSON in ignored `private-data/`. The root contains integer `schema_version` set to `1`, plus optional `weather` and `terrain` blocks. Each block has:

| Field | Requirement |
| --- | --- |
| `provider`, `product`, `resolution`, `reference` | Non-empty strings. State the native interval, grid spacing or station support, and a product reference. Keep private paths and query parameters out of the reference. |
| `source_kind` | `station observation` or `historical estimate` for weather. `terrain model` for terrain. |
| `max_distance_m` | Positive radius in metres, at most 100,000. Choose it based on product support and expected representativeness. |
| `max_time_offset_s` | Weather only. Positive UTC time tolerance in seconds, at most 10,800. |
| `points` | Explicit numeric observations. Each row contains decimal `latitude_deg` and `longitude_deg`. |

Weather rows also contain ISO 8601 `time_utc` with a UTC offset (for example, a trailing `Z`), and at least one of numeric `air_temperature_c`, `wind_speed_mps`, and `wind_from_deg`. Use true-north meteorological direction and metres per second. Terrain rows contain `elevation_m`. Document the vertical reference in the product description or reference. Unknown optional weather fields may be omitted or null. Use station or grid-cell coordinates.

Weather selects the nearest eligible observation to each bin midpoint in normalized squared time and haversine distance. Terrain uses nearest in-space elevation. Both enforce their supplied radii and do not extrapolate past those bounds. No carry-forward or cross-source filling is applied. Summaries weight valid bins by distance and report the represented fraction. When wind direction is absent, non-calm wind speed can still contribute to wind-speed coverage, while the along-track component remains missing. Finite resolution, point-to-route separation and weather exposure constrain interpretation.

### Whole-activity weather summaries

When an archive contains sourced aggregates, the same local JSON may include an `activity_weather` block. Use the weather provenance fields above and replace the spatial bounds and `points` with `summaries`. Each row uses the FIT session's UTC start in the `activity_start_utc` field, the same three optional weather value fields and a positive integer `source_sample_count`. The `field_sample_counts` object records the reported number of contributing records per present value, bounded by the total. An optional integer `spatial_anchor_count` records the source's reported anchors. The start must match the selected recording and is withheld from the browser.

Whole-activity values are displayed separately from the segment metrics. Archive field counts describe prior enrichment and cannot establish the source resolution or weather at a point on the route. When the ride has no time- and location-resolved wind, the reference profile projects one fixed vector from the archived speed and wind-from direction onto each local heading. Its variation shows the effect of heading changes under that assumption. The reference values do not populate point-weather coverage. A product or averaging method absent from the archive is left unspecified.

Potential sources if the archive lacks observations include Environment and Climate Change Canada hourly stations for local observations, Open-Meteo Historical Weather with an explicitly selected ERA5 product for hourly 2 m temperature and 10 m wind estimates, and Copernicus GLO-30 for a roughly 30 m elevation surface. Product coverage, support and suitability should be checked before using any external values. Obtain explicit owner consent for any request containing exact private coordinates or activity timestamps. [ECCC historical climate data](https://climate.weather.gc.ca/) · [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) · [Copernicus DEM](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)

The public comparison and 35 km Demo Ride 01 use fictional weather, geometry and motion across fixed deterministic inputs. Real-data preview keeps sensor and weather associations local. The browser receives derived aligned profiles and their provenance, including identifiable projected GPS traces. Absolute FIT timestamps, raw source rows and source filenames are omitted. Private storage remains ignored by Git, and the loopback server offers exports only in public fixture mode.
