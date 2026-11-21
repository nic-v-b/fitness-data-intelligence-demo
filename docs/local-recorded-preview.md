# Local recorded-Garmin validation

The public Fitness demo uses fictional data. This **optional local-only** mode checks the
same Explorer UI, GPS route renderer, temporal sampling, FIT quality diagnostics,
and same-route analysis against privately selected Garmin recordings. No FIT input
or position trace should be committed or included in a public screenshot.

## Prerequisites

- Python 3.12 or newer
- `npm ci` from the repository root (installs the pinned Leaflet map renderer)
- One or two Garmin FIT files for running, stored **only under `private-data/`**
- Optional: a local Mapbox `pk.` token file and the official Mapbox attribution
  SVG or PNG, also stored under `private-data/`

The repository ignores `private-data/`, `*.fit`, tokens and ordinary environment
files. Check the staging area before every commit.

## Start the private review

From the repository root:

```powershell
python tools/run_local_recorded_preview.py --run private-data/run-01.fit
```

To compare two recorded runs and view satellite imagery:

```powershell
npm ci
python tools/run_local_recorded_preview.py `
  --run private-data/run-01.fit `
  --run private-data/run-02.fit `
  --mapbox-token private-data/mapbox-token.txt `
  --mapbox-logo private-data/mapbox-logo.svg
```

Open `http://127.0.0.1:8131/`. Stop with `Ctrl+C`.

The satellite background is **one integrated map** with the GPS trace, selected
sample and optional historical run shown as overlays. It starts automatically
when Mapbox assets and Leaflet are available. The Offline button selects the
SVG fallback; missing tiles also return to that fallback. Genuine route data
is visible to the local browser and requested map tiles reveal the map's
visible area and zoom to Mapbox.

## Privacy and scientific limitations

- The private server binds to `127.0.0.1`, rejects unexpected Host and
  cross-site requests, and disables private CSV/JSON exports. Never tunnel
  or publicly proxy this private preview.
- The private FIT inputs can reveal precise home/work routes and timestamps.
  Use only selected activities on a trusted machine.
- A public Mapbox token is not a secret in the browser: use a dedicated,
  appropriately restricted token and monitor usage. Never commit it.
- The public repository must continue to use independently invented data
  for interactive routes. The recorded Garmin examples published in README
  are selected, static images and animations, not interactive GPX/FIT data.
- The local athlete Profile and Planner still use **fictional** longitudinal
  examples. Private FIT ingestion does not turn their illustrative readiness
  or planning rules into individualized clinical advice.
- Satellite availability requires valid local Mapbox assets and an internet
  connection. Automated CI verifies the mapping logic and offline fallback
  without connecting to a real Mapbox account.

## Protected three-run review plus the complete cycling ride

The previously validated protected running-route review is kept separate from
the complete original cycling recording. The complete cycling FIT is admitted
only if its GPS trace agrees with the ride already present in the protected
bundle at several locations along the route.

1. Copy the **existing**, previously inspected `routes.json` from the original
   development workspace's `artifacts/recorded-route-review-500/` to the same
   relative directory under this portfolio-review checkout. Never copy it to
   `docs/` or another Git-tracked directory.
2. Copy your selected full cycling FIT to the ignored `private-data/review/selected-ride.fit` path (or adapt the command to its existing filename). Confirm the recording is already in this checkout's
   ignored `private-data/review/` folder. Keep the previously selected
   restricted Mapbox assets under `private-data/`.
3. Run from the portfolio-review repository root:

```powershell
python tools/run_local_recorded_preview.py `
  --bundle artifacts/recorded-route-review-500/routes.json `
  --cycling private-data/review/selected-ride.fit `
  --mapbox-token private-data/mapbox-public-token.txt `
  --mapbox-logo private-data/mapbox-logo.svg `
  --port 8131
```

**Expected:** three masked running activities with withheld original dates and
totals, plus one **complete cycling FIT**. This is a private loopback session;
it must not be exposed via a reverse proxy, tunnel or deployed application.

The route-protection implementation in `route_privacy.py` excludes areas around
recording endpoints, checks that retained segments do not reconnect across
excluded areas, and preserves gaps in the visualizations. Its exact geometric
criteria and limitations are documented in the source and regression tests.
These safeguards reduce location disclosure but cannot establish anonymity:
familiar terrain may still be recognizable. The complete cycling route is used
only in the private local review; never commit raw FIT data or Mapbox tokens.

To use independently verified **activity-level historical weather** for the
complete cycling ride only, first copy the previously staged private weather
summary to this checkout's ignored `private-data/review/`, then add:

```powershell
  --weather private-data/review/activity-weather-summary.json
```

The weather file must follow the existing `Sources.load` schema, and any
reported weather depends on matching activity timestamps. Protected running
bundle observations deliberately omit original start times, so weather
summaries are **not yet linked to protected running** in this workflow.

The historical running cohort is also intentionally **not merged into the
protected dashboard as full GPS routes**. The earlier cohort staging and
weather sources remain available as local research inputs, but publication
requires separate aggregate-only validation to avoid revealing unmasked
running tracks. Do not use `--cohort` with `--bundle`.
