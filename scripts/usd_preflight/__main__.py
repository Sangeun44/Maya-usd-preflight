"""Re-check a saved scene snapshot with plain Python, no Maya needed.

    python -m usd_preflight scene.snapshot.json --profile profiles/sim_ready.json
    python -m usd_preflight --list
"""
from __future__ import annotations

import argparse
import sys

from .checks import CHECKS, Settings, run_checks
from .model import Scene


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m usd_preflight", description=__doc__.split("\n")[0])
    parser.add_argument("snapshot", nargs="?", help="a .snapshot.json written by batch mode")
    parser.add_argument("--profile", help="JSON profile")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--list", action="store_true", help="list the checks and exit")
    args = parser.parse_args(argv)

    if args.list:
        for item in CHECKS:
            print("%-26s %-8s %s" % (item.id, item.severity, item.title))
        return 0
    if not args.snapshot:
        parser.error("give a snapshot file, or --list")

    with open(args.snapshot) as handle:
        scene = Scene.from_json(handle.read())
    report = run_checks(scene, Settings.load(args.profile))
    print(report.to_json() if args.json else report.format_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
