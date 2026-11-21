"""Run an opt-in local Garmin preview; never expose raw FIT files publicly.

Two independent modes:
  --run: entirely private original FIT sessions and optional private history
  --bundle: previously approved masked running sections from ignored artifacts/
The protected bundle may be paired with one verified, full-length cycling FIT.
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_server, mapbox_options  # noqa: E402
from private_preview import build_private_portfolio  # noqa: E402
from tools.recorded_review_integrator import build_protected_local_preview  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="append", type=Path,
                      help="One or two locally selected untrimmed running FIT files")
    mode.add_argument("--bundle", type=Path,
                      help="Previously approved protected routes.json under ignored artifacts/")
    parser.add_argument("--cycling", type=Path, help="Selected full cycling FIT file")
    parser.add_argument("--weather", type=Path,
                        help="Optional local environmental observations under private-data/")
    parser.add_argument("--cohort", type=Path,
                        help="Private raw-FIT mode only: optional local cohort manifest")
    parser.add_argument("--mapbox-token", type=Path, help="Local restricted Mapbox pk. token file")
    parser.add_argument("--mapbox-logo", type=Path, help="Official Mapbox attribution SVG or PNG")
    parser.add_argument("--port", type=int, default=8131)
    args = parser.parse_args(argv)

    if args.run is not None and len(args.run) not in (1, 2):
        parser.error("Select one or two distinct untrimmed running FIT activities.")
    if args.bundle is not None and args.cohort is not None:
        parser.error("The full-GPS cohort is not exposed in the protected-bundle review.")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be in the range 1..65535.")
    if bool(args.mapbox_token) != bool(args.mapbox_logo):
        parser.error("Mapbox requires both a token file and an official attribution logo.")

    # Both loaders enforce containment in ignored local folders. The HTTP server
    # binds only to 127.0.0.1 and disables JSON/CSV exports for recorded data.
    try:
        if args.bundle is not None:
            dataset, comparison, portfolio = build_protected_local_preview(
                args.bundle.resolve(),
                full_cycling=args.cycling.resolve() if args.cycling else None,
                weather=args.weather.resolve() if args.weather else None,
            )
        else:
            dataset, comparison, portfolio = build_private_portfolio(
                [path.resolve() for path in args.run],
                cycling_path=args.cycling.resolve() if args.cycling else None,
                observation_path=args.weather.resolve() if args.weather else None,
                cohort=args.cohort.resolve() if args.cohort else None,
            )
        mapbox = mapbox_options(args.mapbox_token, args.mapbox_logo)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    with create_server(args.port, dataset, comparative=comparison,
                       portfolio=portfolio, mapbox=mapbox) as server:
        print(f"Local recorded review: http://127.0.0.1:{server.server_port}/", flush=True)
        if not mapbox:
            print("Offline map only. To enable satellite, supply both local Mapbox assets.", flush=True)
        if args.bundle:
            print("Protected running sections from review bundle; cycling is complete only with --cycling.", flush=True)
        print("Loopback-only server. Never tunnel, proxy, or publish its private API.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
