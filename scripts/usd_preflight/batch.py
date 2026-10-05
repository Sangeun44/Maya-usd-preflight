"""Check a folder of Maya scenes without opening Maya's interface.

    mayapy -m usd_preflight.batch scenes/ --out out/ --export

Each scene gets a JSON report in --out and, with --export, a USD file if no
check failed. The exit code is 1 if any scene has errors (2 if batch mode
itself could not run), so a farm job or a CI step fails when a scene does. (From a checkout,
`mayapy preflight_batch.py ...` does the same without setting PYTHONPATH.)
"""
from __future__ import annotations

import argparse
import os
import sys


def find_scenes(paths: list[str]) -> list[str]:
    scenes = []
    for path in paths:
        if os.path.isdir(path):
            for root, _, names in sorted(os.walk(path)):
                scenes.extend(os.path.join(root, n) for n in sorted(names) if n.endswith((".ma", ".mb")))
        else:
            scenes.append(path)
    return scenes


def find_project(scene_path: str, levels: int = 3) -> str:
    """The nearest folder above the scene that has a workspace.mel, or ""."""
    folder = os.path.dirname(os.path.abspath(scene_path))
    for _ in range(levels):
        if os.path.isfile(os.path.join(folder, "workspace.mel")):
            return folder
        folder = os.path.dirname(folder)
    return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayapy -m usd_preflight.batch", description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="+", help="scene files, or folders to search for .ma/.mb files")
    parser.add_argument("--out", default="preflight_out", help="folder for reports and exports")
    parser.add_argument("--profile", help="JSON profile")
    parser.add_argument("--project", help="Maya project that relative texture paths resolve against "
                                          "(default: the nearest folder above each scene with a workspace.mel)")
    parser.add_argument("--export", action="store_true", help="export scenes that pass to USD")
    parser.add_argument("--force", action="store_true", help="export scenes that fail too")
    parser.add_argument("--snapshots", action="store_true",
                        help="also save each scene snapshot, to re-check later without Maya")
    args = parser.parse_args(argv)

    scenes = find_scenes(args.paths)
    if not scenes:
        print("no .ma or .mb files found")
        return 0

    import maya.standalone
    maya.standalone.initialize(name="python")
    from maya import cmds

    from .checks import Settings, run_checks
    from .collect import collect
    from .export import export
    from .report import ERROR, Issue

    if args.export:
        try:
            cmds.loadPlugin("mayaUsdPlugin", quiet=True)
        except RuntimeError:
            print("--export needs the Maya USD plug-in (mayaUsdPlugin), which could not be loaded")
            return 2

    settings = Settings.load(args.profile)
    os.makedirs(args.out, exist_ok=True)
    failed = 0
    for path in scenes:
        stem = os.path.splitext(os.path.basename(path))[0]
        load_error = None
        project = args.project or find_project(path)
        if project:
            cmds.workspace(project, openWorkspace=True)
        try:
            cmds.file(path, open=True, force=True, prompt=False)
        except RuntimeError as error:      # Maya raises on a missing reference but still opens the scene
            load_error = str(error).strip().splitlines()[-1]
        scene = collect()
        if args.snapshots:
            with open(os.path.join(args.out, stem + ".snapshot.json"), "w") as handle:
                handle.write(scene.to_json(indent=1))
        report = run_checks(scene, settings)
        if load_error:
            report.issues.insert(0, Issue("scene.load", ERROR, "", load_error))
        if args.export and (report.ok or args.force):
            target = os.path.join(args.out, stem + ".usda")
            report.issues.extend(export(target, scene=scene))
            report.exported = target
        with open(os.path.join(args.out, stem + ".report.json"), "w") as handle:
            handle.write(report.to_json())
        print(report.format_text())
        if report.exported:
            print("  -> %s" % report.exported)
        failed += not report.ok

    print("\n%d of %d scenes passed" % (len(scenes) - failed, len(scenes)))
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # mayapy can hang or crash while tearing Maya down; the work is done, so leave now.
    os._exit(code)
